import nox


@nox.session(python=["3.7", "3.8", "3.9", "3.10"])
@nox.parametrize("pip", ["22.1.2"])
@nox.parametrize("poetry", ["1.1.13", "1.2.0b2"])
def tests(session, pip, poetry):
    session.install(f"poetry=={poetry}")
    session.install(f"pip=={pip}")
    session.install(".")
    session.install("pytest")
    session.install("pytest-mock")
    session.run("pytest")
