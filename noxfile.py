import nox


@nox.session()
@nox.parametrize("pip", ["22.1.2"])
@nox.parametrize("poetry", ["1.1.13", "1.2.0b2", "1.2.2"])
def tests(session, pip, poetry):
    session.install(f"poetry=={poetry}")
    session.install(f"pip=={pip}")
    session.install(".")
    session.install("pytest")
    session.install("pytest-mock")
    session.run("pytest")
