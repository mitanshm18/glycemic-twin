# Raw data (not in Git)

Put the official CGMacros v1.0.0 download here, or point `SOURCE=` at it anywhere on disk.

- Dataset page: https://physionet.org/content/cgmacros/1.0.0/
- ZIP: https://physionet.org/files/cgmacros/1.0.0/CGMacros_dateshifted365.zip
- Checksums: https://physionet.org/files/cgmacros/1.0.0/SHA256SUMS.txt

License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0. Cite the
PhysioNet record and the CGMacros paper when using it.

Rules:

- These files are read-only. The pipeline opens them for reading and never writes here.
- The ZIP is preferred: its SHA-256 can be checked against PhysioNet's official list
  (`make m1 SOURCE=... SUMS=.../SHA256SUMS.txt`). An extracted folder cannot be checked
  against that list, so the first run pins a local manifest and later runs verify against it.
