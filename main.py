import sys

from assistant.cli import CLIInterface
from assistant.wake_word import WakeWordDetector
from assistant.speech_to_text import SpeechToText
from assistant.parser import parse
from assistant.executor import execute


class OfflineAssistant:

    def __init__(self):

        self.wake = WakeWordDetector()
        self.stt = SpeechToText(model_path="models/vosk-model-small-en-us-0.15")

    def run_voice(self):

        print("Voice Assistant Started")

        while True:

            self.wake.detect()

            command = self.stt.listen()

            parsed_cmd = parse(command)

            execute(parsed_cmd)

    def run_cli(self):

        cli = CLIInterface()
        cli.start()


if __name__ == "__main__":

    assistant = OfflineAssistant()

    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        assistant.run_cli()
    else:
        assistant.run_voice()