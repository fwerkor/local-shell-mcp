<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# مرجع الأدوات

تُبنى هذه الصفحة من MCP tool schemas الفعلية. شغّل `python scripts/generate-tools-reference.py` بعد تغيير public tool surface لتحديث English reference.

تعيد معظم الأدوات `ToolResult` منظمًا يحتوي `ok` و`message` و`data`. يعيد `workspace_open` الحالة المرئية للنموذج المستخدمة لعرض MCP App. تقبل معظم أدوات التنفيذ والملفات `machine` اختياريًا؛ احذفه للعمل على workspace الخاص بالـ controller وحدده للعمل على worker متصل. تُنفذ عمليات Git عمدًا عبر `run_shell` أو أداة shell أخرى بدل wrappers خاصة بـ Git.

## دليل الاختيار

| الحاجة | الأدوات المفضلة |
|---|---|
| مراقبة التنفيذ أو التعاون عليه في ChatGPT | `workspace_open` |
| فحص environment | `environment_get`, `file_tree`, `file_read` |
| تشغيل command قصيرة أو عملية Git | `run_shell` |
| تشغيل مهمة تفاعلية أو طويلة | `shell_start` or `job_start` |
| إجراء تغييرات دقيقة على الملفات | `file_edit` or `file_patch` |
| نقل ملف أو directory | `remote_transfer` |
| اكتشاف capability MCP خارجية | `mcp_tool_search`, then `mcp_tool_inspect` |
| التفاعل مع صفحة | `browser_session`, `browser_snapshot`, then `browser_act` |
| تشغيل browser logic مخصصة | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| العمل على machine بعيدة | استخدم الأداة نفسها مع `machine`؛ استخدم `remote_*` فقط لإدارة workers |

## Workspace تفاعلي

### `workspace_open`

افتح أو أعد استخدام Live Workspace يعرض الـ Logical Session المحددة صراحةً. مرّر session_id النشط الذي أعاده session_manage. لا يستنتج Workspace هوية المهمة من MCP transport؛ مرّر null صراحةً عندما لا توجد Logical Session نشطة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

## Environment وSkills وحالة المهام

### `environment_get`

يعيد version وworkspace وauth وpolicy ومعلومات environment محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `skill_list`

يسرد Agent Skills المثبتة دون تحميل instructions. يبقى MCP tool surface ثابتًا؛ وتظهر إضافة/إزالة Skill directories في الاستدعاء التالي.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

يحمّل Skill مثبتة بالاسم الدقيق الذي أعادته `skill_list`. يعيد instructions الكاملة لـ `SKILL.md` وpaths الملفات المتعلقة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

يقرأ ملف text related واحدًا من Skill مثبتة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

يفحص ملفات النص في local workspace بحثًا عن secrets شائعة قبل commit أو push.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

أدر Logical Session دائمة واحدة. ينشئ start مهمة جديدة ويعيد session_id الخاص بها. يتابع resume فقط session_id الصريح الذي قدّمه المستخدم أو الموجود بالفعل في هذه المحادثة. تتطلب كل الإجراءات عدا start قيمة session_id. الإجراءات: start, resume, get, report, finish, cancel, delete. يقبل report الحقول summary/findings/next/blockers/objective/label، ويتطلب delete Session نهائية.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `label` | `string \| null` | `null` |  |
| `objective` | `string \| null` | `null` |  |
| `summary` | `string \| null` | `null` |  |
| `findings` | `array[string] \| null` | `null` |  |
| `next` | `string \| null` | `null` |  |
| `blockers` | `array[string] \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `plan_manage`

أدر Goal mode الاختياري للـ Logical Session المحددة صراحةً. يفعّل plan نشط المتابعة التلقائية بعد 15 دقيقة من دون نشاط agent، بحد أقصى 10 محاولات. يجب أن يكون session_id هو المعرّف الدائم نفسه الذي أعاده session_manage. الإجراءات: start, get, update, block, resume, finish, cancel. يتطلب start objective وsteps، ويتطلب finish أن تكون كل steps completed أو skipped.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string` | required |  |
| `objective` | `string \| null` | `null` |  |
| `steps` | `array[object] \| null` | `null` |  |
| `step_id` | `string \| null` | `null` |  |
| `status` | `string \| null` | `null` |  |
| `text` | `string \| null` | `null` |  |
| `note` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `audit_tail`

يقرأ أحدث entries من local audit log.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells وjobs

### `run_shell`

يشغّل command shell واحدة غير تفاعلية محليًا أو على machine بعيدة. استخدمه لـ build وtest وpackage-manager وGit وinspection التي ينبغي أن تنتهي سريعًا. للعمليات الطويلة أو التفاعلية أو streaming استخدم `shell_start` أو `job_start`. تسمح حقول purpose/explanation الاختيارية بذكر سبب التشغيل.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `run_python`

يكتب ويشغّل script Python قصيرة محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `shell_start`

يبدأ shell تفاعلية دائمة محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `shell_send`

يرسل input إلى persistent local/remote shell session.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `shell_read`

يقرأ output الحديث من persistent local/remote shell session.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `shell_stop`

ينهي persistent local/remote shell session.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `shell_list`

يسرد persistent shell sessions محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `job_start`

يبدأ long-running job متتبعة محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `job_list`

يسرد jobs المتتبعة محليًا أو على machine بعيدة. تُعرض jobs النشطة أولًا، وتُقيّد قيمة `limit` إلى النطاق 1-1000.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `job_tail`

يقرأ output الحديث لـ tracked local/remote job.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `job_stop`

يوقف tracked local/remote job.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `job_retry`

يعيد تشغيل tracked local/remote job متوقفة أو خرجت.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

## الملفات والنقل

### `file_list`

يسرد الملفات وdirectories محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `file_tree`

يعيد directory tree مدمجة محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `file_glob`

يعثر على paths عبر glob محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `file_grep`

يبحث في محتوى الملفات محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `file_read`

يقرأ ملفًا أو قائمة files محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `image_view`

يعرض PNG أو JPEG أو GIF أو WebP كمحتوى image MCP أصلي محليًا أو على machine بعيدة. استخدمه بدل `file_read` عند الحاجة إلى فحص بصري. تعيد الصور البعيدة استخدام file-transfer protocol الحالي، لذلك لا يحتاج worker إلى RPC خاص بالصور.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `file_write`

يكتب ملف text UTF-8 محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `file_edit`

يطبق edit نصي exact واحدًا أو أكثر على ملف محلي أو بعيد. يحتوي كل edit على old وnew و`replace_all` اختياري؛ ويجب أن يتطابق old بدقة بما في ذلك whitespace وindentation.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `file_delete`

يحذف ملفًا أو directory محليًا/بعيدًا. يحذف `recursive=false` الملفات أو directories الفارغة؛ أما غير الفارغة فتحتاج `recursive=true` ويجب استخدامه بحذر.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `file_patch`

يفحص ويطبق unified diff أو file_patch envelope محليًا أو عن بعد.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `remote_transfer`

يبدأ job متتبعًا ينسخ ملفًا أو مجلدًا بين controller والأجهزة البعيدة. تستخدم uploads البعيدة chunks raw-binary قابلة للاستئناف؛ أدر النقل باستخدام `job_list` و`job_tail` و`job_stop` و`job_retry`.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

يجب تحديد واحد على الأقل من `source_machine` و`destination_machine`. تشير endpoints المحذوفة إلى workspace الخاص بالـ controller؛ ويمكن أن يكون المصدر ملفًا أو مجلدًا.

### `link_create`

ينشئ URL مؤقتًا يمكن للbrowser الوصول إليه لملف محلي. افتراضيًا تكون الاستجابة attachment download؛ اضبط `inline=true` للعرض المباشر في browser أو صورة Markdown. Links هي public bearer URLs محمية بـ high-entropy token وTTL وحد تنزيل اختياري وrevocation صريح.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

يسرد URLs تنزيل الملفات المحلية المولدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

يلغي URL تنزيل ملف محلي مولد.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Dynamic MCP gateway

### `mcp_manage`

يسجل أو يسرد أو يجلب أو يفعّل أو يعطّل أو refresh أو يحذف أو يحدّث environment/headers المعزولة لـ dynamic MCP servers. استخدم transport `stdio` مع command/args/cwd أو `streamable_http` مع url. يتم حفظ secret env/header values بشكل خاص ولا تعاد أبدًا.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `transport` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `args` | `array[string] \| null` | `null` |  |
| `cwd` | `string \| null` | `null` |  |
| `url` | `string \| null` | `null` |  |
| `env` | `object \| null` | `null` |  |
| `headers` | `object \| null` | `null` |  |
| `enabled` | `boolean` | `true` |  |
| `overwrite` | `boolean` | `false` |  |
| `refresh` | `boolean` | `true` |  |
| `key` | `string \| null` | `null` |  |
| `value` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

يبحث cached lightweight tool summaries من dynamic MCP servers المفعلة. لا تدخل dynamic tools في `tools/list` لهذا server؛ استخدم اسم `<server>:<tool>` المعاد مع `mcp_tool_inspect` قبل الاستدعاء.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

يعيد full cached schema لأداة MCP ديناميكية باسم `<server>:<tool>`. اعمل refresh للـ server بـ `mcp_manage` إذا كان cache stale.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

يستدعي cached dynamic MCP tool باسم `<server>:<tool>`. اكتشفها بـ `mcp_tool_search` وافحص schema بـ `mcp_tool_inspect` أولًا. تفتح external MCP connections فقط أثناء هذه المكالمة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

يبدأ أو يسرد أو يغلق أو ينظف persistent high-level browser sessions محليًا أو عن بعد. يمكن لـ `start` فتح URL أو إعادة استخدام persistent `profile_id` أو تحميل `storage_state_path`؛ ويمكن لـ `close` حفظ storage state.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `browser` | `string` | `"chromium"` |  |
| `headless` | `boolean` | `true` |  |
| `width` | `integer` | `1440` |  |
| `height` | `integer` | `1000` |  |
| `url` | `string \| null` | `null` |  |
| `wait_until` | `string` | `"domcontentloaded"` |  |
| `profile_id` | `string \| null` | `null` |  |
| `storage_state_path` | `string \| null` | `null` |  |
| `save_storage_state_path` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `browser_snapshot`

يلتقط persistent browser page: title وURL ونصًا مرئيًا محدودًا وعناصر تفاعلية ذات refs قصيرة ثابتة مثل `e1` وأخطاء page/network حديثة وpath screenshot اختياري. استخدم refs مباشرة كـ targets لـ `browser_act` حتى تتنقل الصفحة أو تؤخذ snapshot جديدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `browser_act`

ينفذ structured actions في persistent browser session. يدعم navigate وnew_page وclose_page وclick وfill وtype وselect وpress وcheck وuncheck وhover وwait وwait_for_text وwait_for_url. يمكن أن يكون `target` ref من `browser_snapshot` مثل `e1` أو CSS selector. استخدم `browser_run_script` فقط عندما لا تكفي high-level actions.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

### `browser_run_script`

يشغّل script Python Playwright كاملة محليًا أو على machine بعيدة.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.

## أتمتة واجهة سطح المكتب

### `gui_list`

List visible desktop application windows and GUI backend capabilities locally or remotely.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_state`

Observe one desktop window before acting. Returns its accessibility elements plus an optional native MCP screenshot and a short-lived state_id. Prefer element_id actions; coordinate actions are relative to the observed window and are rejected if the window moved or resized.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `screenshot` | `boolean` | `true` |  |
| `include_elements` | `boolean` | `true` |  |
| `max_elements` | `integer` | `300` |  |
| `max_depth` | `integer` | `12` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_action`

Execute GUI actions against a fresh gui_state observation locally or remotely. The state_id is single-use. Prefer semantic element_id targeting; raw x/y coordinates are window-relative. Supported actions are click, double_click, right_click, move, scroll, drag, type, key, set_value, focus, and wait.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `state_id` | `string` | required |  |
| `actions` | `array[GuiAction]` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

## إدارة remote workers

### `remote_manage`

يدير remote workers عبر action=invite أو list أو revoke أو rename. invite يقبل name/workdir/ttl_s؛ revoke يحتاج machine؛ rename يحتاج machine وnew_name.

| المعامل | النوع | مطلوب/default | الوصف |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session لاستدعاء الأداة هذا. مرّر session_id الذي أعاده session_manage أثناء العمل على المهمة. استخدم null فقط عندما لا توجد Logical Session نشطة. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

عند تحديد `machine`، يتطلب الاستدعاء أيضًا `remote:use` ويعمل عبر بروتوكول remote worker.
