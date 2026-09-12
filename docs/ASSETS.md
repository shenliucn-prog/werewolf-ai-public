# Asset provenance and licensing

The project's source code is licensed under the [MIT License](../LICENSE).
Third-party components retain their own licenses. Portrait artwork is separate
from the code license; the maintainer's publication authorization is recorded below.

## Portraits

The maintainer declares that the 12 NPC portraits are their own AI-generated artwork. The maintainer subsequently confirmed that
the portraits are their own and authorized their use in this project and
publication with the repository.

This records the maintainer's declaration and authorization, not an independent
rights audit. The generation tool/model was not supplied. That missing detail is
not treated as a pending maintainer approval for this project's publication.

The authorization does not place the portraits under MIT or grant a general
standalone reuse license. Contact the maintainer for other uses of the artwork.

The development originals retain their generation metadata and are not overwritten
by release preparation. The history-free candidate builder removes only the
independent EXIF ImageDescription fields `ServiceUser`, `Time` and `ContentId` in
the exported copies, zeroing the entire old allocation. It retains ServiceProvider,
all non-EXIF PNG chunks (including pixel data), and the separate AIGC UserComment
provenance/signature envelope byte-for-byte. No image resampling is performed.

The exported copies are **metadata-redacted derivatives**, not byte-identical
originals. Signature fields are preserved, but their validity has not been
verified and is not asserted after this change. Producer/propagator trace IDs and
signature-envelope timestamps remain for provenance; this is not a claim that all
identifiers have been removed. Local export manifests record which files/fields changed and their hashes;
these packaging artifacts are not committed to source. Do not
strip the entire EXIF block. See the [publication plan](PUBLICATION_PLAN.md).

## Additional eighteen portraits and characters

The expanded library adds eighteen original fictional characters and portraits
generated with OpenAI's built-in image generation tool at the maintainer's
request. No real-person references were used. See [character and prompt notes](CHARACTERS.md).
These new PNGs carry caBX provenance manifests rather than the original twelve's
EXIF format; release preparation preserves their complete bytes. Manifest
signatures have not been independently verified. Artwork is not automatically
covered by the code's MIT license.

The expanded bilingual persona descriptions were AI-assisted for this project;
the historical declaration below applies to the original persona material.

## Original persona material

NPC names, descriptions, and catchphrases are maintained in the persona files
and localization code. The maintainer
confirmed that they personally wrote the persona descriptions and catchphrases.
The outstanding text-authorship question is therefore resolved by the maintainer's
declaration; no repeat confirmation is required.

This declaration concerns authorship, not whether historical nicknames or other
identifying metadata should be published. Local records are excluded under the [publication policy](PUBLIC_RELEASE.md). It does not change the portrait
license or constitute an independent legal rights audit.
