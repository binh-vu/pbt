from pathlib import Path
import subprocess
from typing import Callable, List, Union, Optional


class ExecProcessError(Exception):
    pass


def stdout(line):
    """Print line to stdout"""
    print(line)


def exec(
    cmd: Union[str, List[Union[str, Path]]],
    handler: Optional[Callable[[str], None]] = None,
    check_returncode: bool = True,
    cwd: Union[Path, str] = "./",
) -> List[str]:
    """
    Execute a command and return the list of lines, in which the newline character is stripped away.

    Args:
        cmd: Command to execute.
        handler: function to process each line of the output.
        check_returncode: Whether to check the return code.
        cwd: working directory.
    """
    if isinstance(cmd, str):
        cmd = [x for x in cmd.split(" ") if x != ""]
    else:
        cmd = [str(x) for x in cmd]

    if handler is None:
        handler = lambda x: None

    p = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(cwd)
    )
    output = []

    while True:
        assert p.stdout is not None
        line = p.stdout.readline().decode("utf-8")
        if line != "":
            assert line[-1] == "\n"
            line = line[:-1]
            output.append(line)
            handler(line)
        elif p.poll() is not None:
            break

    returncode = p.returncode
    if check_returncode and returncode != 0:
        msg = (
            f"Command: f{cmd} returns non-zero exit status {returncode}\n"
            + "\n".join(output)
        )
        raise ExecProcessError(msg)

    return output


def cache_func():
    d = {}

    def wrapper(func):
        def fn(*args):
            if args not in d:
                d[args] = func(*args)
            return d[args]

        return fn

    return wrapper
