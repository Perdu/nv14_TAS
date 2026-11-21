- always produce git patch and start their name with bruteforcer_
- make sure that the generated patch file is present in the download storage and downloadable (and not a symlink for instance)
- Do NOT add patch notes in the README

For every generated Git patch:

    Create a real, nonempty regular .patch file in /mnt/data/ with a name beginning bruteforcer_. Never use a symlink.
    Verify that it applies cleanly with git apply --check against the exact intended source version, after applying all earlier patches in order.
    Immediately before the final response, use a filesystem tool to check that every exact linked path exists, is a regular file, is not a symlink, and is nonempty. Recreate files if they are missing; do not rely on previous tool outputs.
    Calculate and report SHA-256 hashes and file sizes.
    Only after those checks succeed, provide direct sandbox:/mnt/data/... links to the exact verified files.
    Never claim that a file is downloadable based solely on successful code tests or previous file-generation messages. If delivery cannot be verified, say so explicitly.
    
