[中文](USAGE.zh.md) | **English**

# Order Dispatch Tester — Usage Guide

> Maintenance convention: **every feature change must update this document** (new or changed screens, fields, behavior) **and its Chinese counterpart [USAGE.zh.md](USAGE.zh.md)**. Both language versions must stay in sync.

[Project README](../README.md) · [中文 README](../README.zh-CN.md)

## 1. Startup and deployment

- Requirements: Python 3.8+, standard library only.
- Start: `python run.py --port 5088 --rds http://<rds-host>:8088`, then open <http://127.0.0.1:5088> in a browser.
  - Options: `--port`, `--host` (default 127.0.0.1), `--rds/--base` dispatcher URL, `--data DIR` data directory (default: the project directory, or the environment variable `ORDER_TESTER_DATA`), `--adapter` (default `rds`).
  - Data directory contents: `settings.json`, `drafts.json`, `sent_orders.json`, `scene_cache.json` (the last successfully loaded scene), `templates/`, `logs/`, `maps/`.
- Windows: double-click `start_tester.bat` (runs in the background with `pythonw` and opens the browser; if `pythonw.exe` is not on PATH, set the environment variable `PYW`).
- The dispatcher address saved in the page (written to `settings.json`) takes precedence over the `--rds` startup option.
- Updating a deployment: replace the program files (back them up first) → stop the old `run.py --port 5088` process → start it again in the background with `pythonw run.py --port 5088` → open the home page and confirm it returns 200. The data directory (templates, station pools, orders) is not affected.
- Self-test: `python -m unittest -v`; `tools/fake_rds.py` is a fake RDS (`--port`, `--scene-delay SECONDS` simulates a slow scene, `--scene-fail` simulates a failure).

## 2. Config & Dispatch (配置与派单) — four sub-tabs

The sub-tabs at the top switch between pages; the current sub-tab is remembered in the browser's localStorage. Every sub-tab shows a persistent **summary** line at the top: current template · number of stations in each pool in use · strategy · planned order count (format: `Template {tpl} · {pools} · {strat} · {n} orders planned`), with a **Generate orders** (生成运单) button next to it (the same button as on the 4th sub-tab).

### 2.1 Connection (连接)
- Dispatcher URL (调度系统地址), Poll interval (s) (轮询间隔(秒)), Stuck threshold (s) (卡死阈值(秒)), Vehicle idle threshold (s) (车辆静止阈值(秒)), Dispatcher adapter (调度适配器), Language (界面语言) (Chinese/English, kept in sync with the top-right switch).

### 2.2 Pools (站点池)
- **Load stations from scene** (从调度系统场景加载站点): **the only manual entry point for loading the scene**. In one go it pulls the stations, pre-points, robot groups, scene geometry (routes) and point cloud (via `/downloadScene` when necessary) from RDS `/scene`, and it always fetches afresh; the Map tab reuses the result directly (see section 7).
- The station table is read-only: it can be searched and filtered by type, shows positions and pre-points, and lists only stations already in a pool (see "Station list on the Pools tab (read-only)" below). Stations can be added to a pool in only two ways: click a station on the **Map** tab, or use **Paste stations manually** (comma/newline separated station names).
- **Station pools**: the defaults are `start` and `end`. You can create any pool (letters/digits/underscore, not starting with a digit) with **New pool**, **Rename** it (custom pools; references in templates are updated accordingly), **Delete pool**, **Swap** two pools, and click × to remove a single station. Pools the current template does not use are marked "(not used by the template)".
- **"In use" pools** only look at **enabled** steps: the pools used by enabled `Pool` steps, and the pools that enabled `Pre-point of step` steps finally point to (following the reference chain). A pool referenced only by disabled steps (for example `start` in a "drop-only" template where the pick and pre-point Wait steps are both disabled and only the drop is kept) does not count as in use: it is not shown in the summary, generating/auto dispatch does not require it to be non-empty, and the order's Stations column shows only the end station (with `pickPre` empty). The empty-pool validation (frontend and backend) applies only to pools in use.
- **Strategy** (生成策略): Random (no reuse) (随机不重复; default count = size of the first pool), Round-robin (轮询; order i takes the i-th station of each pool, count = largest pool), Cartesian product (全组合).
- Options: "No repeated station within an order"; "Avoid reusing stations within a batch (sampling without replacement)".

### 2.3 Template (订单模板)
- Template list: New / Copy / Delete / Import / Export (files are in `<data>/templates/*.json`), and you can switch to **Raw JSON mode**; the right side shows a live **Sample order preview (dispatcher JSON)** (the JSON the dispatcher actually receives).
- The step table lets you add (**+ Add step**), delete, enable/disable, and reorder steps (buttons or **Drag to reorder**). See section 3 for the fields.

### 2.4 Dispatch & Generate (派单参数与生成)
- **Robot group** (机器人组; RDS `group`; if none is chosen the field is omitted), **Vehicle** (指定车辆; empty = auto assign), **Priority** (优先级), **label (optional)**.
- **Block-by-block** (逐块下发; off by default) and **Block poll (s)** (逐块轮询(秒); default 1): see "Block-by-block dispatch" below. The checkbox state is saved with the configuration and applies to later clicks of **Send selected** and to auto dispatch.
- **Manual pre-point map** (前置点手动映射): one `station=pre-point` per line; for several values per station write `station=pre-point1|pre-point2` (the first is the default). It takes precedence over scene derivation; `station:pre-point` and `station pre-point` are also accepted, and anything after `#` is a comment. Invalid syntax (for example `AP1=LM1, LM2`, `AP1=`, or the same station on two lines) is marked red below the input box, and generation fails with an error that names the line number.
- **Orders N** (订单数 N; tick "=default" to follow the strategy default) → **Generate orders**: this only generates drafts ("Draft"); send them later from the Test Orders tab.
- If the template uses pre-points but the scene has not been loaded yet, the scene is loaded automatically before generating (with an overlay; a failure shows a dialog); stations without a pre-point are reported and skipped.

## 3. Order template fields

| Field | Description |
|---|---|
| On (启用) | Disabled steps generate no block |
| ID | Unique within the template, must not be empty or duplicated; used for variable references and the default block suffix |
| Name (名称) | Display only (may be Chinese) |
| Block suffix `blockSuffix` (UI label: suffix) | RDS `blockId = order ID + suffix`, default `-<ID>` |
| Location (位置来源) `location` | `Pool` (站点池; `{"type":"pool","pool":"<pool name>"}`, picks a station from the pool according to the strategy; the dropdown lists all pools); `Pre-point of step` (另一步骤站点的前置点; `{"type":"pre","step":"<step ID>"}`, looks up the manual map first, then derives AP→LM from the scene); `Fixed station` (固定站点; `{"type":"fixed","station":"<station>"}`) |
| Pre-point selection `select` / `selArg` | `pre` steps only. Which candidate to use when the station has several candidate pre-points; see "Multiple pre-points" below |
| Operation (动作) `operation` | For example `JackLoad`, `JackUnload`, `ForkLoad`, `Wait`, `Script`; `none` means move only |
| Args (JSON) (参数 args) | Must be a JSON object; multi-line edit box, its height can be dragged vertically |
| variableShape | Optional; after ticking "on" enter `head` / `tail` (numbers, in meters), which are written to the block's `variableShape` |

**args variables** (substituted inside strings; an unknown variable is an error):
`{start}` `{end}` `{<pool>}` the station picked from that pool for this order; `{pickPre}` `{dropPre}` the pre-points of the start/end stations; `{pre:<pool>}` the pre-point of that pool's station; `{stationOf:<step ID|stepN>}` the station of a step; `{preOf:<step>}` the pre-point of a step's station; `{orderId}` the order ID.

### Multiple pre-points (pre-point selection strategy)

When the scene is loaded, **all** candidate pre-points of each station are stored (including direction, distance and whether it is an LM, kept in the scene cache) and listed by number below the station table's "Pre-point" column, for example `1.LM1(in 1.0m) 2.LM2(in 3.0m) 3.LM3(out 2.0m)`. Candidate order: the one specified in the station's properties → in and LM → out and LM → other in → other out; within a group, nearest first. The first one is the default pre-point (same as before).

`pre` steps get an extra selector under "Location" (`location.select` / `location.selArg` in the template JSON):

| Strategy | select / selArg | Meaning |
|---|---|---|
| nearest (default) | omitted, or `nearest` | The 1st candidate; with a manual mapping, the first manual value. Old templates are unaffected |
| by number | `index` / `2` | The N-th candidate (starting from 1) |
| by name / wildcard | `name` / `LM1*` | The first candidate whose name equals or matches the wildcard (`*`, `?`) |
| by direction | `dir` / `in` or `out` | The first candidate with direction in / out |
| random per order | `random` | One candidate chosen at random for each order |

- With a manual mapping, the candidate list = the manually written values (in the order written; direction/distance are taken from the scene information; a point that is not in the scene has an unknown direction, so selecting by direction will not match it).
- Variables can also carry a strategy, written after `@`: `{preOf:<step>@in}`, `{preOf:<step>@out}`, `{preOf:<step>@#2}`, `{pre:<pool>@name=LM1*}`, `{preOf:<step>@random}`; without `@` they behave as before.
- Within one order, the same station + the same strategy is chosen only once (also for random), so steps and variables get the same result.
- When nothing matches, generation fails with an error naming the step, station, strategy and all candidates, for example: `no pre-point matches dir=out for station AP2 [step pre] (candidates: LM20(in))`.
- The pre-point actually chosen is recorded for each order (`preChosen` in the order record); when the Test Orders tab's Stations column shows ⓟ, hover over it to see "step: station → pre-point (strategy)".
- Example: `examples/templates/pre_select_demo.json`.

The built-in `default` template = the original five-block RDS deadlock test order (pre-point Wait → pick → Script → drop → fork lift).

## Map tab

- Layers (**Point cloud**, **Routes**, **Stations**, **Vehicles**): next to Point cloud you can choose the point size thin / medium / bold / extra bold (screen pixels, unchanged when zooming); the choice is saved (settings + browser).
- The **Station heading** layer: stations that have an angle in the scene get a purple heading arrow (RDS field `dir`, in radians; `angle`/`theta`/`yaw` are also recognized); stations without an angle are not drawn; stations with `ignoreDir=true` ("ignoreDir: any heading") get a light-colored arrow; hovering over a station shows its name, type and angle (degrees). Angles are saved with the scene cache.
- The point cloud comes from the scene load (see section 7); you can also add to it with **Upload .smap** or by entering a local path (**or local path**). The Map tab itself does not trigger a scene load.

## 4. Robots

- Robot groups are parsed from `/scene` when the scene is loaded; the **Robot group** dropdown in Dispatch parameters comes from here.
- The Robots tab shows robots partitioned by group (those without a group go under "Ungrouped"), with columns: Position, Station, Order, Order state, Dispatchable, Connected, Blocked, Battery, Idle; a robot that has an order and has been idle longer than the "Vehicle idle threshold (s)" is marked red (suspected deadlock).

## 5. Test Orders tab

- **Grouping**: the Drafts group is pinned at the top; sent orders are grouped by Batch (newest batch first); the group header shows the batch time, order count, per-state counts, stuck count and total duration; groups can be collapsed, and **Select this group (filtered)** is available. Orders sent by older versions are assigned to "Legacy batch" groups inferred from the log or from time gaps.
- **Sending**: tick drafts → set **Interval (s)** for this batch and **Max open orders** (0 = unlimited) → **Send selected**; you can also **Stop sending**, **Delete selected drafts**, and **⇄ Swap start/end of selected drafts** (rebuilt with the current template).
- **Sent**: **Cancel selected**, **Cancel all open test orders** (terminate), **Clear sent list** (drafts are kept), and view the JSON (**View** in the JSON column).
- **Filter**: State (multi-select; none checked = all), Vehicle contains, robot group, Stations (matches "start→end"), Order ID, **Stuck only**, **Hide finished**, **Clear filter**; shows "{n}/{total} match".
- **Sorting**: click a column header to toggle ascending/descending (Order ID, Stations, Vehicle, State, Created, Age, Unchanged, Started/Ended, Duration, etc.); the sort setting is remembered in localStorage.

## 6. States and stuck detection

- States: Draft, SENT, CREATED, TOBEDISPATCHED, RUNNING, WAITING, FAILED, FINISHED, STOPPED, SEND_FAIL, etc.
- Terminal states (polling stops): FINISHED, STOPPED, MANUAL_FINISHED, CANCELED/CANCELLED, SKIPPED (and SEND_FAIL when sending failed). **FAILED is not terminal** (RDS can recover); monitoring continues and the order can be judged stuck.
- **Possibly stuck**: the order is not finished, **has a vehicle assigned**, and its "Unchanged" duration > the stuck threshold. A change in state/block state, or vehicle movement > 5 cm or rotation > 2°, counts as a change; orders without an assigned vehicle are not counted. The stuck count is shown on the tab, in group headers and in the map summary.

## 7. Scene loading and the overlay

- **Entry points for loading**:
  - Manual: only **Load stations from scene** on the Pools tab (stations + pre-points + robot groups + geometry + point cloud loaded together, ignoring the cache and fetching afresh).
  - **Scene cache**: after every successful load, the server keeps the scene (stations, pre-points, robot groups, routes, point cloud) in memory and persists it to `<data>/scene_cache.json` (including the load time), so it survives a service restart. A failed load does not overwrite the last successful cache.
  - When the page is opened/refreshed, it **unconditionally restores from the cache**, without contacting RDS and without showing the overlay; the station area and the map tab's status line show "Scene loaded at HH:MM" (with the date if not today).
  - Only clicking **Load stations from scene** fetches from RDS again and updates the cache; Generate orders prefers the cached pre-points.
  - With no cache: if the pools are non-empty when the page opens, the scene is loaded automatically once; if Generate orders needs pre-points and the scene has not been loaded, it is loaded automatically.
  - The Map tab **no longer has** a "reload scene/point cloud" button and never triggers a load itself; when no scene is loaded, its status line tells you to go to the Pools tab to load it ("Scene not loaded: go to Config & Dispatch → Pools and click "Load stations from dispatcher scene""). The Map tab can still add to the point cloud via **Upload .smap** or a local path.
- **Overlay and progress bar**: while loading, a full-screen translucent overlay + spinner + "Loading scene… (/scene can take 30-60 s)" is shown, with a progress bar, the current stage and the elapsed seconds ("{s} s elapsed") below it (Chinese/English); clicks and keyboard input are blocked, and it disappears automatically when done.
  - Stages: "Requesting /scene, waiting for the dispatcher…" (waiting for the response; the bar scrolls) → "Downloading scene" (with Content-Length it shows a percentage and downloaded/total size; without it, it shows downloaded KB/MB and the bar scrolls) → "Parsing stations / routes" → "Parsing point cloud" → "Writing cache".
  - When `/scene` contains no point cloud (`normalPosList`), the point cloud is taken from the map, adding these stages: "Downloading map (/downloadScene)" (also with a percentage or MB) → "Unpacking / parsing map" → "Downsampling point cloud" (shows the raw point count); when the map has not changed it shows "Map unchanged, reusing point cloud cache" and skips parsing and downsampling.
  - **The point cloud cache is content-based**: `pointcloud_cache.json` is keyed by the hash of the map file content; when the map downloaded from /downloadScene has the same content as last time, the file in `maps/` is not overwritten and the cache is reused directly; it is re-parsed only when the content changed. When `/scene` routes are already available, parsing the map only extracts the point cloud and does not recompute the routes.
  - The server runs the load as a background job (`/api/scene_geom?async=1` starts it, `/api/scene_job?id=` queries progress), and the page queries every 0.3 seconds; multiple simultaneous loads share one job. All load entry points go through this job.
- **Failure messages**:
  - A failure of a manual load or a load triggered by generating: a dialog reports the error, and the station area shows the error and a **Retry** button.
  - A failure of the automatic load at page open: **no dialog**, the error is only shown in the station area.
  - The server treats a non-2xx HTTP status from `/scene`, a network error, a non-JSON-object response or a parse exception as a failure (it is never treated as a successful load with 0 stations).
- **Browser cache**: pages and static assets are served with `Cache-Control: no-store`, and `app.js` carries a version number `?v=<modification time>`, so a refresh after deployment takes effect immediately.

### Station heading: automatic backfill of old caches
Stations in an old `scene_cache.json` have no `dir`. When the cache is restored at startup, if no station has an angle, a background task parses `dir`/`ignoreDir` from the local smap (the smapPath in the settings, or the map auto-downloaded under `maps\`), adds them to the cache and writes it back, without downloading the map again. It is logged as `dir_backfill`. If there is no local smap, just load the scene once more (the unit of the `dir` field from /scene is radians).

### Display of multiple pre-points
When a station has several direct LM routes, all of those LMs are candidates (for example AP140259 → LM142652 / LM140258).
- The default pre-point (the first in the candidate list, i.e. the nearest "in" LM) is shown in bold in the pre-point info line; the other candidates follow it, joined with `/`, in gray.
- On the map, the dashed line of the default candidate is darker and those of the other candidates are lighter.
- When there is at least one LM candidate, non-LM neighbors (for example AP200 on an AP-AP link) are no longer counted as candidates, so that index and random never pick an AP.

### Station list on the Pools tab (read-only)
The list shows only stations that have been added to some pool, and no longer lists all the stations in the scene.
- Columns: Station, Type, Position, Pre-point (the default pre-point in bold, followed by the candidate list), Pools (colored tags; a station can belong to several pools).
- The Search box and Type filter only filter among these selected stations.
- The list itself cannot add stations. There are only two ways to add stations:
  - click a station on the **Map** tab;
  - use **Paste stations manually**.
- To remove a station, click the × on its tag in the pool.
- When the list is empty, a hint about the ways above is shown ("No station is in any pool yet. Add stations by clicking them on the Map tab or via "Paste stations manually".").

### Orders cancelled in RDS
- Polling keeps tracking a FAILED order (FAILED is not terminal and can still recover in RDS) until it enters a real terminal state.
- Terminal states include: FINISHED, STOPPED, MANUAL_FINISHED, CANCELED/CANCELLED, WITHDRAWN, TERMINATED. After entering a terminal state:
  - the duration is frozen and the end time is recorded;
  - it is no longer counted as stuck;
  - it is counted under that state in the statistics;
  - you can tick CANCELED/STOPPED in the State filter to pick out such orders.
- For an order cancelled (withdrawn) in the RDS UI, RDS deletes the record outright: `/orderDetails/<id>` returns `{"code":50002,"msg":"order details is empty"}`.
  - After the tool receives "order not found" 3 times in a row, it records the order as **CANCELED (gone from RDS)**, displayed in purple. The end time is the moment of the first failed lookup, and the log records `order_change gone=true`.
  - A network error or timeout alone does not lead to this judgment.
  - If the order can be found again in between, the counter is reset and tracking continues with the actual state returned by RDS.
- The tool only uses read-only GET requests to query order state and never sends any write operation to RDS.

### Block-by-block dispatch (逐块下发; block-by-block)
- When off (the default), behavior is exactly as before: `POST /setOrder` carries all blocks at once, with `complete: true`.
- When ticked, each order is tracked independently (the multiple orders of a batch/auto dispatch can proceed at the same time):
  1. `POST /setOrder`: carries only the first block, `complete: false`.
  2. The tool polls `GET /orderDetails/<id>` at the **Block poll (s)** interval, and when the `state` of the last sent block is `FINISHED`, it does `POST /addBlocks` with body `{"id": <order ID>, "blocks": [next block], "complete": false}`.
  3. Right after the last block has been appended successfully, `POST /markComplete` with body `{"id": <order ID>}` (seal the order).
  - Success criterion: HTTP 200 and a returned `{"code": 0}`; after 5 consecutive failures of addBlocks/markComplete, the tool stops.
- Stop conditions: **appending never stops as long as the order has not reached a terminal state**. It stops only when the order `state` is `FINISHED` / `STOPPED` (cancelling in the tool = RDS terminate → STOPPED; also CANCELED/WITHDRAWN/TERMINATED/SKIPPED), and the reason is written to the log (`inc_stopped`). Order or block `FAILED` / `Error`, `SUSPENDED`, `WAITING`, unknown states, an orderDetails request that fails/times out/finds no such order, and consecutive addBlocks failures all only log a warning (`inc_warn`), pause and keep polling; once things recover, appending continues (in real tests RDS briefly reports an order as FAILED and then recovers to RUNNING).
- Entries of block-by-block orders (saved in sent_orders.json) that older versions marked "stopped" because of `order FAILED` / `order Error` / order not found / repeated addBlocks failures are automatically restored to appending at startup or at the next poll (log `inc_revived`), and continue from the blocks already present in orderDetails without appending duplicates.
- The State column of the Test Orders tab is followed by a `blocks k/N` tag: blue = appending ("appending blocks"), green ✓ = all appended and sealed ("all blocks appended, marked complete"), orange = order/block abnormal, paused until recovery, still polling ("order/block abnormal, paused until recovery (still polling)"), red = order terminal (FINISHED/STOPPED), stopped ("order terminal (FINISHED/STOPPED), appending stopped"; hover for details). The status line at the top shows "{n} block-by-block orders open".
- An unsealed order's state in RDS after all blocks are finished is `WAITING` (not FINISHED); it becomes FINISHED only after it is sealed.
- Tool restart: the appending progress is saved in `sent_orders.json`, and tracking resumes automatically after startup (log `inc_resume`; the tag's hover text shows "resumed after tool restart"). On resume, the block list returned by orderDetails is authoritative, and blocks already in RDS are not appended again.
- Log events: `inc_start`, `inc_add`, `inc_resync`, `inc_error`, `inc_done`, `inc_stopped`.
- Checked against the official RDSCore HTTP API documentation (Feishu wiki "HTTP API" → Orders / Action blocks):
  - `setOrder`'s `complete` (bool, false = do not seal; `addBlocks` can follow); `addBlocks` body `{id, blocks, complete?}` (`complete` needs ≥0.1.8.22090102; this tool does not use it for sealing); `markComplete` body `{id}` (`{idList}` is also supported; this tool does not use it).
  - Success criterion: HTTP 200 and `code` equal to 0 **or absent**; error codes 40000/50000/50001/50002/50003 (addBlocks on a sealed order returns 50003 "order is complete").
  - Order states: CREATED / WAITING / RUNNING / SUSPENDED / FINISHED / FAILED / STOPPED / Error / TOBEDISPATCHED; action block states additionally include POSTING and MANUAL_FINISHED.
  - Block-by-block appending: the next block is appended only when the previous block is `FINISHED` or `MANUAL_FINISHED` (manually finished); when a **block** is `FAILED` / `STOPPED` / `Error`, only a warning is logged (the tag turns orange, "order/block abnormal, paused until recovery") and polling continues, and appending resumes after the block recovers and reaches `FINISHED`/`MANUAL_FINISHED`; an **order** that is `FAILED` / `Error` likewise only pauses (orange tag); appending stops only when the order `state` is a terminal `FINISHED` / `STOPPED` (or cancelled). SUSPENDED, WAITING, POSTING and unknown states only wait and do not stop.
  - Note: by default RDS allows addBlocks on a non-existent order ID to **create the order automatically** (parameter CreateNewOrderWhileAddBlocks), so before every append the tool first confirms with orderDetails that the order still exists; if the order is not found, it stops and does not append any more.
