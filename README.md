**BackPack v1.9.0, built unchanged from upstream source.**

Based on BackPack by Amin Mohammadi (AminMGMT)
https://github.com/AminMGMT/BackPack

- Upstream tag `v1.9.0`, commit `dfd29d56546ff0bf877fce97a91a0cda757ba6f2`. No change to the code.
- Upstream published only source for v1.9.0. These archives use upstream's own `make release` layout (one file, `backpack`, at the top) so `doctor-dns.sh` can pin and install them.
- Built with go1.26.9, `CGO_ENABLED=0 -trimpath -buildvcs=false -ldflags '-s -w'`. Each build ran twice with the same hash, after `go mod verify`, `go vet` and upstream's full test suite (normal and `-race`).
- `backpack-v1.9.0-source.tar.gz` is the exact source built (AGPL-3.0). `LICENSE` and `NOTICE` are upstream's.
- If upstream publishes binaries for this version, use those.

| file | sha256 |
|---|---|
| backpack_linux_amd64.tar.gz | `17d6dc185df5b37976d87cf2c9fea2f202871a0b27aa2a7cb336fef1efbba618` |
| backpack_linux_arm64.tar.gz | `8ceda2644052827b72102af7a9f9a62660b304aea9f40f5a35d04bc89a3ef24c` |
| backpack (amd64, inside) | `a76b5d507e163d9213ac2feb25248f2a2418fb22ff92f37fda6f6e4881a10c8f` |
| backpack (arm64, inside) | `feebb6bba4dae09b14c060c6603c2ca147c46243b4509ad45b448203d966a3c7` |
| backpack-v1.9.0-source.tar.gz | `1a69f22e313a0924a5ffd0fe0ccd8401a9e1541c37cbf15a2c06439434445199` |
