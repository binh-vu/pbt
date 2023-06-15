from pep508_rs import Requirement


def test_pep508_spec():
    spec = Requirement(
        'requests [security,tests] >= 2.8.1, == 2.8.* ; python_version > "3.8"'
    )
    print(spec.name, spec.extras, spec.version_or_url)
    print(spec.marker)
