# ForgeCore Runner Core Beta

ForgeCore Runner Core is a local-first self-hosted GitHub Actions runner manager for Umbrel.

## Beta 24

Beta 24 returns Runner Core to the original ForgeCore architecture: the Beelink owns runner state and GitHub is the job broker, not the dashboard database.

- Runner identity remains persistent on the Beelink.
- Online / Busy / Offline comes from local heartbeat and GitHub runner job hooks.
- Normal dashboard refresh does not query GitHub.
- Repository discovery is cached for one hour and can be explicitly refreshed.
- Start / Stop / Restart use local state and do not call GitHub.
- The dashboard is reorganized into **Home**, **Workflows** and **Runners**.
- Workflows are local ForgeCore profiles with user-defined names and stable routing labels.
- Renaming a workflow profile does not change its routing label.
- Unused old workflow profiles can be deleted immediately.
- Profiles still assigned to runners are protected until those runners are edited.
- Runner Edit and Remove remain visually stable until local runner-manager state confirms the operation.

The release gate passed in one self-hosted job:
1. Python local-first contract
2. Dashboard UX + no background GitHub polling
3. Runner-manager heartbeat + job hooks
4. API boot smoke
5. Package integrity + exact payload validation
6. Real self-hosted runner E2E

Version: 0.1.0-beta.24

Source branch: `clean-beta/local-first-v24`

Source commit: `d2ac04a951bd5144b0408a2fc98ed7d6012810d5`
