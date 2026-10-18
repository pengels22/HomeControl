# Main Branch Protection Recommendation

Configure GitHub branch protection for `main` with:

- Required status check: `checks / Test`
- Required status check: `checks / Compile`
- Required status check: `checks / Diff check`
- Required status check: `checks / Active configuration safety checks`
- Pull requests required before merge.
- Branch required to be up to date before merge where practical.
- Force pushes and branch deletion disabled.

This repository does not change GitHub protection settings automatically.
