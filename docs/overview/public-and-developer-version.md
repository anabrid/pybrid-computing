# Public and Developer Version

`pybrid`, in the form of the packages `python-computing` and `python-computing-native`
is available in two versions: the public/stable and the internal/private version.
The latter is reserved for anabrid employyes and project partners with an API.

Please note that all up-to-date versions of anabrid products, including
`pybrid`, are always compatible. Reverting even only one of the packages to an older
version can lead to majpr **incompatibilities**.

!!! warning `Protobuf` versioning

    While the protobuf protocol has an internal version number and versioning infrastructure,
    in the current - development - phase, its version is still pinned to 0.1.0. 
    During this phase, only _version bundles_ of all packages that use the underlying 
    protocol version are compatible. In doubt, please always use the most recent build
    across the full stack.

### Recognizing build versions from the version number

pybrid-computing uses semantic versioning with the following conventions:

- **Released versions**: `X.Y.Z` (e.g., `0.11.5`) - these versions are generally _tagged_ and
are the only versions that are released to the public on PyPi
- **Development versions**: `X.Y.Z.devN+g<commit>` (e.g., `0.11.6.dev3+g5c75b35`) - development
versions used in internal development, created from a single code commit and
CI/CD run.

## Installing the public version

Assuming you have set up `uv` as described in [the getting started guide](../user-guide/getting-started/setup.md),
both packages can now be installed simply through PyPi, i.e.,

```bash
uv pip install pybrid-computing pyredacc
```

That's it! Updates can generally be retrieves with `uv pip install -U`.

## Installing internal versions

Internal versions, the "bleeding edge", is hosted on anabrid's Gitlab server.
You will need an `anabrid` Gitlab account and set up an API
token:
1. Go to `User settings` (click on your portrait) and move to `Personal Access Tokens`
2. Click `Add new token`
3. Enter a self-chosen name and select the `read_repository`, `read_virtual_registry`, `read_registry`, `read_api`.
permissions.
4. Note down the generated token.

In order to automatically retrieve your images, this information should be stored permanently so you
avoid having to `export ...` this in each terminal window. In your `~/.bashrc`, add the following two lines:

```bash
export CI_REGISTRY_USER=<your gitlab user name, e.g. thuerck>
export CI_REGISTRY_PASSWORD=<the token you generated above>
```

With this in place, you can now directly install from the Gitlab PyPi infrastructure:
```bash
uv venv --python 3.13
uv pip install pybrid-computing --prerelease=allow --index-url https://__token__:<TOKEN>@lab.analogparadigm.com/api/v4/projects/pybrid-computing%2Fpybrid-computing/packages/pypi/simple
```