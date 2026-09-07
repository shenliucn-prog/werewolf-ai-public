# Building a release candidate

Follow the [public-data boundary](PUBLIC_RELEASE.md) and [asset policy](ASSETS.md).
Export into a new directory outside this checkout:

```sh
python scripts/prepare_release.py --output ../release-candidate --archive
```

The exporter excludes runtime and research records even if accidentally tracked.
It preserves portrait pixels and the separate provenance envelope, redacting only
the reviewed independent EXIF fields. Unknown metadata layouts fail closed.
A generated manifest belongs to the local package, not to the source repository.

Run the Python suite, frontend tests and release checker against the candidate.
Use a reviewed public commit identity and never import private development history.
