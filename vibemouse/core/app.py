from __future__ import annotations

import logging
import threading
from pathlib import Path

from vibemouse.bindings.actions import command_for_legacy_gesture_action
from vibemouse.bindings.resolver import BindingResolver
from vibemouse.core.audio import AudioRecorder, AudioRecording
from vibemouse.core.commands import (
    COMMAND_NOOP,
    COMMAND_SEND_ENTER,
    COMMAND_TOGGLE_RECORDING,
    COMMAND_TRIGGER_SECONDARY_ACTION,
    COMMAND_WORKSPACE_LEFT,
    COMMAND_WORKSPACE_RIGHT,
    EVENT_HOTKEY_RECORD_TOGGLE,
    gesture_direction_to_event,
)
from vibemouse.config import AppConfig, write_status
from vibemouse.core.output import TextOutput
from vibemouse.core.transcriber import SenseVoiceTranscriber
from vibemouse.listener.keyboard_listener import KeyboardHotkeyListener
from vibemouse.listener.mouse_listener import SideButtonListener
from vibemouse.platform.system_integration import (
    SystemIntegration,
    create_system_integration,
)


_LOG = logging.getLogger(__name__)


class VoiceMouseApp:
    def __init__(self, config: AppConfig) -> None:
        if config.front_button == config.rear_button:
            raise ValueError("Front and rear side buttons must be different")

        self._config: AppConfig = config
        self._system_integration: SystemIntegration = create_system_integration()
        self._recorder: AudioRecorder = AudioRecorder(
            sample_rate=config.sample_rate,
            channels=config.channels,
            dtype=config.dtype,
            temp_dir=config.temp_dir,
        )
        self._transcriber: SenseVoiceTranscriber = SenseVoiceTranscriber(config)
        self._output: TextOutput = TextOutput()
        self._binding_resolver: BindingResolver = BindingResolver.from_config(config)
        self._listener: SideButtonListener = SideButtonListener(
            on_event=self._handle_input_event,
            front_button=config.front_button,
            rear_button=config.rear_button,
            debounce_s=config.button_debounce_ms / 1000.0,
            gestures_enabled=config.gestures_enabled,
            gesture_trigger_button=config.gesture_trigger_button,
            gesture_threshold_px=config.gesture_threshold_px,
            gesture_freeze_pointer=config.gesture_freeze_pointer,
            gesture_restore_cursor=config.gesture_restore_cursor,
            system_integration=self._system_integration,
        )
        self._keyboard_listener: KeyboardHotkeyListener = KeyboardHotkeyListener(
            on_event=self._handle_input_event,
            event_name=EVENT_HOTKEY_RECORD_TOGGLE,
            keycodes=config.record_hotkey_keycodes,
            debounce_s=config.button_debounce_ms / 1000.0,
        )
        self._stop_event: threading.Event = threading.Event()
        self._transcribe_lock: threading.Lock = threading.Lock()
        self._workers_lock: threading.Lock = threading.Lock()
        self._workers: set[threading.Thread] = set()
        self._prewarm_started: bool = False

    def run(self) -> None:
        self._listener.start()
        self._keyboard_listener.start()
        self._set_recording_status(False)
        _LOG.info(
            "VibeMouse ready. "
            + f"Model={self._config.model_name}, preferred_device={self._config.device}, "
            + f"backend={self._config.transcriber_backend}, auto_paste={self._config.auto_paste}, "
            + f"enter_mode={self._config.enter_mode}, debounce_ms={self._config.button_debounce_ms}, "
            + f"front_button={self._config.front_button}, rear_button={self._config.rear_button}, "
            + f"prewarm_on_start={self._config.prewarm_on_start}. "
            + "Press side-front to start/stop recording. Side-rear sends Enter."
        )
        self._maybe_prewarm_transcriber()
        try:
            _ = self._stop_event.wait()
        except KeyboardInterrupt:
            self._stop_event.set()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._listener.stop()
        self._keyboard_listener.stop()
        self._recorder.cancel()
        self._set_recording_status(False)
        with self._workers_lock:
            workers = list(self._workers)
        still_running: list[threading.Thread] = []
        for worker in workers:
            worker.join(timeout=5)
            if worker.is_alive():
                still_running.append(worker)
        if still_running:
            _LOG.warning(
                f"Shutdown warning: {len(still_running)} transcription worker(s) are still running"
            )

    def _handle_input_event(self, event_name: str) -> None:
        command_name = self._binding_resolver.resolve(event_name)
        if command_name is None:
            _LOG.debug("Ignoring unbound input event: %s", event_name)
            return
        self._execute_command(command_name, source_event=event_name)

    def _execute_command(
        self,
        command_name: str,
        *,
        source_event: str | None = None,
    ) -> None:
        if source_event is not None:
            _LOG.debug("Resolved input event '%s' -> '%s'", source_event, command_name)

        if command_name == COMMAND_NOOP:
            return
        if command_name == COMMAND_TOGGLE_RECORDING:
            self._toggle_recording()
            return
        if command_name == COMMAND_TRIGGER_SECONDARY_ACTION:
            self._trigger_secondary_action()
            return
        if command_name == COMMAND_SEND_ENTER:
            self._send_enter_command()
            return
        if command_name == COMMAND_WORKSPACE_LEFT:
            return
        if command_name == COMMAND_WORKSPACE_RIGHT:
            return

        _LOG.warning("Ignoring unsupported command '%s'", command_name)

    def _toggle_recording(self) -> None:
        if not self._recorder.is_recording:
            try:
                self._recorder.start()
                self._set_recording_status(True)
                _LOG.info("Recording started")
            except Exception as error:
                self._set_recording_status(False)
                _LOG.exception("Failed to start recording: %s", error)
            return

        try:
            recording = self._stop_recording()
        except Exception as error:
            _LOG.exception("Failed to stop recording: %s", error)
            return

        if recording is None:
            return

        self._start_transcription_worker(recording)

    def _trigger_secondary_action(self) -> None:
        # If recording, stop and transcribe (same as front button stop)
        if self._recorder.is_recording:
            try:
                recording = self._stop_recording()
            except Exception as error:
                _LOG.exception("Failed to stop recording: %s", error)
                return
            if recording is not None:
                _LOG.info("Recording stopped by rear button, transcribing...")
                self._start_transcription_worker(recording)
            return

        # If idle, send Enter
        self._send_enter_command()

    def _send_enter_command(self) -> None:
        try:
            mode = self._config.enter_mode
            if mode == "none":
                _LOG.info("Enter key handling disabled (enter_mode=none)")
                return
            self._output.send_enter(mode=mode)
            _LOG.info("Enter key sent")
        except Exception as error:
            _LOG.exception("Failed to send Enter: %s", error)

    def _on_gesture(self, direction: str) -> None:
        event_name = gesture_direction_to_event(direction)
        if event_name is None:
            _LOG.warning("Gesture '%s' mapped to unknown direction", direction)
            return

        command_name = self._binding_resolver.resolve(event_name)
        if command_name is None:
            _LOG.info("Gesture '%s' recognized with no action configured", direction)
            return
        self._execute_command(command_name, source_event=event_name)

    def _stop_recording(self) -> AudioRecording | None:
        try:
            recording = self._recorder.stop_and_save()
        except Exception as error:
            self._set_recording_status(False)
            raise RuntimeError(error) from error

        self._set_recording_status(False)
        if recording is None:
            _LOG.info("Recording was empty and has been discarded")
            return None
        return recording

    def _start_transcription_worker(self, recording: AudioRecording) -> None:
        worker = threading.Thread(
            target=self._transcribe_and_output,
            args=(recording,),
            daemon=True,
        )
        with self._workers_lock:
            self._workers.add(worker)
        worker.start()

    def _transcribe_and_output(self, recording: AudioRecording) -> None:
        current = threading.current_thread()
        try:
            _LOG.info(
                "Recording stopped (%.1fs), transcribing...", recording.duration_s
            )
            with self._transcribe_lock:
                text = self._transcriber.transcribe(recording.path)

            if not text:
                _LOG.info("No speech recognized")
                return

            route = self._output.inject_or_clipboard(
                text,
                auto_paste=self._config.auto_paste,
            )

            device = self._transcriber.device_in_use
            backend = self._transcriber.backend_in_use

            if route == "typed":
                _LOG.info(
                    "Transcribed with %s on %s, typed into focused input",
                    backend,
                    device,
                )
            elif route == "pasted":
                _LOG.info(
                    "Transcribed with %s on %s, pasted via clipboard",
                    backend,
                    device,
                )
            elif route == "clipboard":
                _LOG.info(
                    "Transcribed with %s on %s, copied to clipboard", backend, device
                )
            else:
                _LOG.warning(
                    "Transcribed with %s on %s, but output was empty", backend, device
                )
        except Exception as error:
            _LOG.exception("Transcription failed: %s", error)
        finally:
            self._safe_unlink(recording.path)
            with self._workers_lock:
                self._workers.discard(current)

    def _safe_unlink(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception as error:
            _LOG.warning("Failed to remove temp audio file %s: %s", path, error)

    def _maybe_prewarm_transcriber(self) -> None:
        if not self._config.prewarm_on_start or self._prewarm_started:
            return
        self._prewarm_started = True

        worker = threading.Thread(
            target=self._prewarm_transcriber,
            args=(self._config.prewarm_delay_s,),
            daemon=True,
        )
        worker.start()

    def _prewarm_transcriber(self, delay_s: float = 0.0) -> None:
        if delay_s > 0:
            _LOG.info("Transcriber prewarm scheduled in %.1fs", delay_s)
            if self._stop_event.wait(timeout=delay_s):
                return

        try:
            self._transcriber.prewarm()
            _LOG.info("Transcriber prewarm complete")
        except Exception as error:
            _LOG.warning("Transcriber prewarm skipped: %s", error)

    def _set_recording_status(self, is_recording: bool) -> None:
        payload = {
            "recording": is_recording,
            "state": "recording" if is_recording else "idle",
        }
        try:
            write_status(self._config.status_file, payload)
        except Exception:
            return
