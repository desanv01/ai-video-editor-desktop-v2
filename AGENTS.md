# Desktop V2 RC worker coordination

For RC8 and subsequent Desktop V2 RC worker chats, main chat `01a0e5d8-d40c-7d22-9a88-744b738e9a9b` owns planning, review, tests, all GitHub actions, and release acceptance. Workers execute only assigned implementation, build, or packaging tasks and report changed files, completion, and blockers to main. The user authorizes bidirectional worker reports. Do not run unassigned broad tests or audits or take GitHub actions.

The user's model preference is Astra for main and Sol Medium for workers. Fast mode is preferred, but the task API does not expose a Fast mode switch.
