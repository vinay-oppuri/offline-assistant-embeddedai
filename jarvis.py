import sys
from assistant.parser import parse
from assistant.executor import execute
from assistant.cli import CLIInterface


def main():

    # If arguments provided → direct command
    if len(sys.argv) > 1:

        command = " ".join(sys.argv[1:])
        parsed_cmd = parse(command)

        execute(parsed_cmd)

    # Otherwise open interactive CLI
    else:

        cli = CLIInterface()
        cli.start()


if __name__ == "__main__":
    main()