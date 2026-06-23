import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def crm_server():
    port = get_free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py", "--port", str(port), "--no-browser", "--demo"],
        cwd=str(Path(__file__).parent.parent.absolute()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    url = f"http://127.0.0.1:{port}/"
    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate()
        proc.wait()
        raise RuntimeError("Server failed to start")

    yield url

    proc.terminate()
    proc.wait()


def test_audio_feedback(crm_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome-for-testing",
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
            ],
        )
        context = browser.new_context()
        page = context.new_page()

        # Inject the mock script before loading the page
        mock_script = """
        window.AudioContextMockCalls = [];
        class MockOscillatorNode {
            constructor(ctx) {
                this.ctx = ctx;
                this.frequency = {
                    setValueAtTime: (val, time) => {
                        window.AudioContextMockCalls.push({ method: 'oscillator.frequency.setValueAtTime', value: val, time });
                    },
                    exponentialRampToValueAtTime: (val, time) => {
                        window.AudioContextMockCalls.push({ method: 'oscillator.frequency.exponentialRampToValueAtTime', value: val, time });
                    },
                    linearRampToValueAtTime: (val, time) => {
                        window.AudioContextMockCalls.push({ method: 'oscillator.frequency.linearRampToValueAtTime', value: val, time });
                    }
                };
            }
            connect(dest) {
                window.AudioContextMockCalls.push({ method: 'oscillator.connect', destination: dest });
            }
            start(time) {
                window.AudioContextMockCalls.push({ method: 'oscillator.start', time });
            }
            stop(time) {
                window.AudioContextMockCalls.push({ method: 'oscillator.stop', time });
            }
        }
        class MockGainNode {
            constructor(ctx) {
                this.ctx = ctx;
                this.gain = {
                    setValueAtTime: (val, time) => {
                        window.AudioContextMockCalls.push({ method: 'gain.gain.setValueAtTime', value: val, time });
                    },
                    linearRampToValueAtTime: (val, time) => {
                        window.AudioContextMockCalls.push({ method: 'gain.gain.linearRampToValueAtTime', value: val, time });
                    },
                    exponentialRampToValueAtTime: (val, time) => {
                        window.AudioContextMockCalls.push({ method: 'gain.gain.exponentialRampToValueAtTime', value: val, time });
                    }
                };
            }
            connect(dest) {
                window.AudioContextMockCalls.push({ method: 'gain.connect', destination: dest });
            }
        }
        class MockAudioContext {
            constructor() {
                this.state = 'running';
                this.currentTime = 100.0;
                this.destination = { name: 'destination' };
                window.AudioContextMockCalls.push({ method: 'constructor' });
            }
            createOscillator() {
                window.AudioContextMockCalls.push({ method: 'createOscillator' });
                const osc = new MockOscillatorNode(this);
                this.lastOsc = osc;
                return osc;
            }
            createGain() {
                window.AudioContextMockCalls.push({ method: 'createGain' });
                return new MockGainNode(this);
            }
            resume() {
                window.AudioContextMockCalls.push({ method: 'resume' });
                return Promise.resolve();
            }
        }
        window.AudioContext = MockAudioContext;
        window.webkitAudioContext = MockAudioContext;
        """
        page.add_init_script(mock_script)

        page.goto(crm_server)
        page.wait_for_selector(".app")

        # Wait for data bootstrap to complete
        # Wait for data bootstrap to complete
        page.wait_for_function("() => typeof state !== 'undefined' && state.data")

        # Ensure localStorage defaults or is set
        __audio_setting = page.evaluate(
            "localStorage.getItem('sto-crm-audio-feedback')"
        )
        # Since localStorage was empty, the default state should be audioFeedback = true
        assert page.evaluate("state.audioFeedback") is True

        # Test Case 1: Trigger success toast and verify sound is played
        page.evaluate("window.AudioContextMockCalls = []")
        page.evaluate("toast('Success operation', 'success')")
        page.wait_for_timeout(200)

        calls = page.evaluate("window.AudioContextMockCalls")
        assert len(calls) > 0
        methods = [c["method"] for c in calls]
        assert "createOscillator" in methods
        # Verify the success frequency sweep: from C5 (523.25) to G5 (783.99)
        success_set_freq = [
            c for c in calls if c["method"] == "oscillator.frequency.setValueAtTime"
        ]
        success_ramp_freq = [
            c
            for c in calls
            if c["method"] == "oscillator.frequency.exponentialRampToValueAtTime"
        ]
        assert len(success_set_freq) == 1
        assert success_set_freq[0]["value"] == 523.25
        assert len(success_ramp_freq) == 1
        assert success_ramp_freq[0]["value"] == 783.99

        # Dismiss the success toast
        page.evaluate("dismissCurrentToast()")
        page.wait_for_timeout(300)

        # Test Case 2: Trigger warning toast and verify sound is played (2 tones)
        page.evaluate("window.AudioContextMockCalls = []")
        page.evaluate("toast('Warning occurred', 'warning')")
        page.wait_for_timeout(200)

        calls = page.evaluate("window.AudioContextMockCalls")
        methods = [c["method"] for c in calls]
        # Two oscillators created
        assert methods.count("createOscillator") == 2
        warning_freqs = [
            c["value"]
            for c in calls
            if c["method"] == "oscillator.frequency.setValueAtTime"
        ]
        assert warning_freqs == [440.0, 440.0]

        # Dismiss the warning toast
        page.evaluate("dismissCurrentToast()")
        page.wait_for_timeout(300)

        # Test Case 3: Trigger error/danger toast
        page.evaluate("window.AudioContextMockCalls = []")
        page.evaluate("toast('Critical error', 'danger')")
        page.wait_for_timeout(200)

        calls = page.evaluate("window.AudioContextMockCalls")
        methods = [c["method"] for c in calls]
        assert "createOscillator" in methods
        danger_set_freq = [
            c for c in calls if c["method"] == "oscillator.frequency.setValueAtTime"
        ]
        danger_ramp_freq = [
            c
            for c in calls
            if c["method"] == "oscillator.frequency.linearRampToValueAtTime"
        ]
        assert len(danger_set_freq) == 1
        assert danger_set_freq[0]["value"] == 700.0
        assert len(danger_ramp_freq) == 1
        assert danger_ramp_freq[0]["value"] == 120.0

        # Dismiss the danger toast
        page.evaluate("dismissCurrentToast()")
        page.wait_for_timeout(300)

        # Test Case 4: Click toggler in System Menu to disable sound
        # Expand system menu
        page.click("#systemMenuBtn")
        page.wait_for_selector("#audioToggle")
        assert page.locator("#audioToggle").get_attribute("aria-checked") == "true"

        # Toggle it OFF
        page.click("#audioToggle")
        # Wait for toggle toast
        page.wait_for_timeout(100)

        # Check localStorage and state
        assert (
            page.evaluate("localStorage.getItem('sto-crm-audio-feedback')") == "false"
        )
        assert page.evaluate("state.audioFeedback") is False
        assert page.locator("#audioToggle").get_attribute("aria-checked") == "false"

        # Dismiss the status toggle success toast
        page.evaluate("dismissCurrentToast()")
        page.wait_for_timeout(300)

        # Verify no audio play call is made when audioFeedback is false
        page.evaluate("window.AudioContextMockCalls = []")
        page.evaluate("toast('Another message', 'success')")
        page.wait_for_timeout(200)

        calls = page.evaluate("window.AudioContextMockCalls")
        assert len(calls) == 0

        # Toggle it ON again
        if not page.is_visible("#audioToggle"):
            page.click("#systemMenuBtn")
            page.wait_for_selector("#audioToggle")
        page.click("#audioToggle")
        page.wait_for_timeout(100)
        assert page.evaluate("localStorage.getItem('sto-crm-audio-feedback')") == "true"
        assert page.evaluate("state.audioFeedback") is True
        assert page.locator("#audioToggle").get_attribute("aria-checked") == "true"

        # Close browser session
        browser.close()
