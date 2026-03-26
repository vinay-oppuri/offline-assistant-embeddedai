from assistant.parser import parse
from assistant.executor import execute


class CLIInterface:

    def __init__(self):
        pass

    def start(self):

        print("Jarvis CLI Assistant")
        print("Type 'exit' to quit\n")

        while True:

            command = input("jarvis> ")

            if command == "exit":
                print("Goodbye")
                break

            parsed_cmd = parse(command)

            execute(parsed_cmd)