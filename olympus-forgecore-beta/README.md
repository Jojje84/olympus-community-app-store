# ForgeCore Runner Core Beta

ForgeCore Runner Core is a local-first self-hosted GitHub Actions runner manager for Umbrel.

## Beta 28

Beta 28 fixes repository-specific runner selection and makes multi-repository routing explicit.

- Repository matching is normalized and case-insensitive.
- Assign runner lists specific runners registered to the selected repository first.
- "Any runner registered to this repository" is an explicit fallback, not the default.
- If a repository has no ForgeCore runner, the assignment dialog tells you directly and offers to create one for that repository.
- Create workflow uses the same repository-aware runner selection.
- A new **Repositories** view makes multi-repo setups first-class.
- Each repository shows its ForgeCore runners and provides **Add runner** and **Workflows** actions.
- Workflow cards show the routing chain: **Repository → Workflow → Runner → This ForgeCore Node**.
- Runner cards show the repository and persistent ForgeCore Node ID so you can see which Beelink-managed runner belongs to which repo.

The full Beta 28 validation passed on the real self-hosted ForgeCore runner.

Version: 0.1.0-beta.28

Source branch: `clean-beta/repo-routing-v28`

Source commit: `e1de639716497453ed055509d290e39c0dfd82d2`
