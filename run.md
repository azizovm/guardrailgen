# How to run GuardrailGen, step by step

This guide assumes you know nothing about this project. You only need to be
able to copy a command, paste it into a terminal, press Enter, and type a
sentence. Do the steps in order and do not skip any.

## What is this, in one paragraph?

A small robot (a TurtleBot3) drives around a simulated house. An AI model
(an LLM) decides how the robot moves. You, the "operator", type a safety rule in
plain English, for example *"Never enter the kitchen."* GuardrailGen turns that
sentence into a checked, machine-readable rule, and a safety filter then blocks
every robot command that would break the rule. You will see the robot in a 3D
window.

## Before you start

- **Computer:** Windows 10/11 with at least 16 GB RAM and about 30 GB free disk.
- **Time:** the first setup takes 1 to 2 hours (mostly downloads). Afterwards,
  starting the experiment takes about 5 minutes.
- **Groq account:** needed only for the "real AI" part (Step 13 onwards).
  Everything before it works without one. Groq may bill you or rate-limit you.

### How to read the commands below

- A box marked `powershell` is pasted into **Windows PowerShell**
  (Start menu, type "PowerShell", open it).
- A box marked `bash` is pasted into the **Ubuntu** terminal
  (Start menu, type "Ubuntu", open it).
- Paste the **whole box**, then press Enter. Wait until the text stops moving
  and you see a prompt again (something ending in `$`) before the next box.
- When Ubuntu asks `[Y/n]`, type `y` and press Enter.
- When Ubuntu asks for a `password`, type your Ubuntu password (nothing appears
  on screen while you type, that is normal) and press Enter.
- To paste in the Ubuntu terminal, right-click or press `Ctrl+Shift+V`.
- To stop a running program in a terminal, press `Ctrl+C`.

---

## Part A: One-time setup

### Step 1: Install Ubuntu 22.04 inside Windows (WSL)

Open **PowerShell as Administrator** (right-click PowerShell, "Run as
administrator") and paste:

```powershell
wsl --install -d Ubuntu-22.04
```

Restart the computer when asked. After the restart, an Ubuntu window opens by
itself (if not, open "Ubuntu 22.04" from the Start menu). It asks you to choose
a **username** and **password**. Write the password down; you will need it.

Check that it worked, in PowerShell (normal, not admin):

```powershell
wsl -l -v
```

You should see `Ubuntu-22.04` with `VERSION 2`.

### Step 2: Install ROS 2 Humble (the robot software framework)

In the **Ubuntu** terminal, paste this whole box:

```bash
sudo apt update && sudo apt install -y software-properties-common curl git python3-pip nano
sudo add-apt-repository -y universe
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
sudo apt update && sudo apt upgrade -y
sudo apt install -y ros-humble-desktop python3-colcon-common-extensions python3-rosdep
```

This takes a while (it downloads a few GB). Then paste:

```bash
sudo rosdep init; rosdep update
```

(If it says `default sources list file already exists`, that is fine.)

### Step 3: Install Gazebo (the 3D simulator) and robot packages

```bash
sudo apt install -y ros-humble-gazebo-ros-pkgs ros-humble-gazebo-msgs ros-humble-gazebo-plugins \
  ros-humble-xacro ros-humble-joint-state-publisher ros-humble-geometry2 \
  ros-humble-cartographer ros-humble-cartographer-ros ros-humble-navigation2 ros-humble-nav2-bringup \
  ros-humble-dynamixel-sdk ros-humble-teleop-twist-keyboard
```

Check it:

```bash
gazebo --version
```

You should see `Gazebo multi-robot simulator, version 11...`.

### Step 4: Build the TurtleBot3 robot workspace

```bash
mkdir -p ~/turtlebot3_ws/src && cd ~/turtlebot3_ws/src
git clone -b humble-devel https://github.com/ROBOTIS-GIT/turtlebot3_msgs.git
git clone -b humble-devel https://github.com/ROBOTIS-GIT/turtlebot3.git
git clone -b humble-devel https://github.com/ROBOTIS-GIT/turtlebot3_simulations.git
```

### Step 5: Download SafeLLMRA (the base safety filter) and patch the robot model

```bash
cd ~ && git clone https://github.com/TUM-CPS-HN/SafeLLMRA.git
cd ~/SafeLLMRA && git checkout 9e9eee5431ee08830f6524d6b09d2014bc3e343b
python3 -c "import zipfile,os; zipfile.ZipFile(os.path.expanduser('~/SafeLLMRA/Turtlebot/turtlebot3_waffle.zip')).extractall('/tmp/tb3_models')"
cp -r /tmp/tb3_models/turtlebot3_waffle /tmp/tb3_models/turtlebot3_waffle_pi ~/turtlebot3_ws/src/turtlebot3_simulations/turtlebot3_gazebo/models/
```

The last line replaces two robot models with SafeLLMRA's versions (a lighter
laser scanner), as SafeLLMRA's own instructions require.

Now build the TurtleBot3 workspace:

```bash
source /opt/ros/humble/setup.bash
cd ~/turtlebot3_ws && colcon build --symlink-install
```

Wait until it prints `Summary: ... packages finished`. Warnings (`stderr`) are
fine; the word `Failed` is not.

### Step 6: Install SafeLLMRA's Python parts and build it

```bash
pip3 install openai==0.28
cd ~/SafeLLMRA/Turtlebot/pyzonotope && pip3 install .
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash
cd ~/SafeLLMRA/Turtlebot && colcon build --symlink-install
```

Again, wait for `Summary: ... packages finished`.

You do **not** need to put an API key into SafeLLMRA's source files, even
though SafeLLMRA's own README says so. GuardrailGen supplies the key from a
separate file (Step 9).

### Step 7: Put the GuardrailGen folder somewhere and tell Ubuntu where it is

Copy the `guardrailgen` folder (the folder containing this `run.md`) anywhere
on your Windows disk, for example your Desktop. Then find its Ubuntu path:
open the folder in Windows Explorer, click the address bar, and copy the path
(for example `C:\Users\anna\Desktop\guardrailgen`).

In Ubuntu, first convert it to a Linux path. **Replace only the text between
the single quotes** with your own path, and do not add any extra `"` quotes:

```bash
wslpath 'C:\Users\anna\Desktop\guardrailgen'
```

It prints something like `/mnt/c/Users/anna/Desktop/guardrailgen`. If it
prints an error or a path without slashes, check your quotes and try again.
Then save that printed path (again, replace the text between the single quotes):

```bash
sed -i '/export GG=/d' ~/.bashrc
echo "export GG='/mnt/c/Users/anna/Desktop/guardrailgen'" >> ~/.bashrc
source ~/.bashrc
cd "$GG" && ls
```

You should see files like `README.md`, `run.md`, `scripts`, `src`. From now on,
`cd "$GG"` always brings you to the project folder.

### Step 8: Install GuardrailGen's Python dependencies

```bash
cd "$GG"
python3 -m pip install --target "$HOME/.cache/guardrailgen/python310-packages" \
    -r requirements-validation.txt -r requirements-solver.txt
```

These go into a private folder so they do not disturb the rest of Ubuntu.

### Step 9: Add your Groq API key (skip if you only want the offline demo)

1. Go to <https://console.groq.com>, sign in, open **API Keys**, click
   **Create API Key**, and copy the key (it starts with `gsk_`).
2. In Ubuntu:

   ```bash
   cd "$GG"
   [ -f .env ] || cp .env.example .env
   nano .env
   ```

3. A text editor opens. Paste your key right after `GROQ_API_KEY=` (no spaces,
   no quotes). The file should look like:

   ```
   GROQ_API_KEY=gsk_yourkeyhere
   GROQ_MODEL=openai/gpt-oss-120b
   ```

4. Save with `Ctrl+O`, then Enter, then exit with `Ctrl+X`.

Never share this file or paste the key anywhere else.

### Step 10: Check that everything is installed (no robot, no AI yet)

```bash
cd "$GG"
bash scripts/run.sh demo
```

You should see example verdicts `SAFE`, `UNSAFE`, and `UNKNOWN`. Then run the
automatic tests:

```bash
bash scripts/test.sh --ros
```

The last line should say something like `... passed` (a few `skipped` are
fine). If you see `failed`, stop and check "If something goes wrong" below.

### Step 11: Build the simulation stack

```bash
cd "$GG"
bash scripts/setup_stack.sh
```

It should end with `Ready. In each terminal: source scripts/stack_env.sh`.

**Part A is done. You never need to repeat Steps 1 to 11.**

---

## Part B: Running the robot experiment

The experiment uses **five Ubuntu terminals** at the same time, each with one
job. Open a new Ubuntu terminal for each (Start menu, "Ubuntu", or `Ctrl+Shift+T`
in Windows Terminal to open a new tab).

**In every one of the five terminals, first paste:**

```bash
cd "$GG" && source scripts/stack_env.sh
```

Nothing visible happens; that is expected. Forgetting this is the most common
mistake: the programs would then run the old, unmodified SafeLLMRA.

> Shortcut: in Windows PowerShell, inside the `guardrailgen` folder, running
> `.\scripts\start_stack.ps1` opens all five tabs and starts terminals 1 to 4
> for you. Use `.\scripts\start_stack.ps1 -Offline` for the no-AI version of
> Step 12. If the tabs do not appear, just do it manually as below.

### Step 12 (recommended first): Offline dry run, no AI and no cost

This checks that the whole pipeline works without calling Groq. In **terminals
2 and 3 only**, additionally paste this before their commands below:

```bash
export GUARDRAILGEN_OFFLINE=1
```

Then continue with Steps 13 to 18 exactly as written. The robot will be driven
by a simple built-in program instead of the AI. Afterwards, close all five
terminals and start over from Part B (without the `OFFLINE` line) for the real
AI run.

### Step 13: (Real AI runs only) Limit how many AI calls may be made

To avoid surprise costs, in **terminals 2, 3 and 4**, paste before their
commands:

```bash
export GUARDRAILGEN_MODEL_CALL_LIMIT=30
```

Without it, up to 120 calls may be made in one episode.

### Step 14: Terminal 1, start the 3D house

```bash
python3 scripts/prepare_house.py
ros2 launch guardrailgen turtlebot_house.launch.py assets_dir:="$GUARDRAILGEN_ROOT/generated/house"
```

A window called **Gazebo** opens with a house, a small robot, an **orange
rectangle** (the "kitchen" the robot must not enter) and a **red circle** (the
goal). The first start can take 1 to 2 minutes. Leave this terminal alone.

### Step 15: Terminal 2, start the AI service

```bash
ros2 run chat_gpt chat_gpt_service
```

Leave it running. It reads your key from `.env`.

### Step 16: Terminal 3, start the AI robot controller

```bash
ros2 run my_robot_controller LLM_robot_controller
```

Leave it running. The robot does not move yet.

### Step 17: Terminal 4, start the safety filter

```bash
ros2 run my_robot_controller safety_check_nonlinear_reachability
```

Leave it running. This is the only program allowed to move the robot; it
checks every command.

Optional check, in terminal 5, that the robot's sensors are ready:

```bash
python3 scripts/stack_health.py
```

### Step 18: Terminal 5, type your safety rule (your first prompt)

While the robot is standing still, paste:

```bash
python3 -m guardrailgen.simulation.stack rule 'Never enter the kitchen.'
```

Wait until you see `validated`, then `active`, version 1, and a formula (the
rule in formal logic). If it fails, the robot keeps no rule and will not start;
read the error text.

Note: in this experiment the kitchen rule is the one that is fully prepared
and checked. Other sentences can be tried with the standalone compiler in
Part C.

### Step 19: Terminal 5, tell the robot to go (your second prompt)

```bash
python3 -m guardrailgen.simulation.stack go 'Go to the goal.'
```

Now watch the Gazebo window. The robot drives from the left toward the red
circle on the right and should go around the orange kitchen. The goal position
is fixed in `config/house_experiment.json`; the sentence itself does not change
where the goal is.

Useful commands in terminal 5 while it runs:

```bash
python3 -m guardrailgen.simulation.stack status   # what is happening now
python3 -m guardrailgen.simulation.stack stop     # stop the robot
```

An episode ends when the robot reaches the goal or after 450 simulated
seconds (about 7.5 minutes of simulation time; on a slow PC this can take
longer in real time). To change it, paste `export GUARDRAILGEN_EPISODE_SECONDS=600`
(or any number) in terminal 4 before Step 17. If you use Step 13's call limit,
a longer episode may need more calls: 30 calls lasted roughly 170 seconds in
earlier runs, so use about 80 for 450 seconds.

### Step 20: Look at the results

Each run is saved in a new folder inside `runs/`, named like
`runs/house_20260921T181931_762807Z/`. You can open it from Windows Explorer
(inside the `guardrailgen` folder). The most useful files:

- `summary.json`: did it reach the goal, how long it took, how many AI calls,
  how many times the filter blocked a command, and any rule violations or
  collisions.
- `trajectory.png` (if present): a picture of the path.
- `events.jsonl`: every single decision, one per line.

To list the newest runs in Ubuntu:

```bash
cd "$GG" && ls -t runs | head
```

### Step 21: Run it again

After one episode the safety filter (terminal 4) finishes by itself and stops
listening, so a new run always needs a restarted terminal 4. Pick **A** (quick,
Gazebo stays open) or **B** (reset absolutely everything).

**Important:** always stop terminals 3 and 4 **before** resetting the robot.
Resetting while the filter runs makes the old episode end with
`simulation_clock_rollback` (the reset command refuses to run while a program
is still driving the robot).

#### A. Quick restart (recommended): keep Gazebo open, new episode

1. In **terminals 3 and 4**, press `Ctrl+C`. Wait until each shows the `$`
   prompt again. Terminal 2 may keep running. (Restart it too with `Ctrl+C` and
   Step 15 if you want its AI call counter back at zero.)
2. In **terminal 5**, put the robot back at the start:

   ```bash
   bash scripts/reset_house.sh
   ```

   It should print `Dedicated house reset to configured spawn`. In Gazebo the
   robot jumps back to the left side.
3. Start **terminal 4** again (Step 17), then **terminal 3** (Step 16):

   ```bash
   ros2 run my_robot_controller safety_check_nonlinear_reachability
   ```

   ```bash
   ros2 run my_robot_controller LLM_robot_controller
   ```

   (If you had set `export` lines from Steps 12 or 13 in these terminals,
   they are still there. In a brand-new terminal, run the `source` line from
   the top of Part B and those `export` lines first.)
4. In **terminal 5**, activate the rule again. The new filter does not
   remember the old rule. Either type it again (Step 18, one or more AI calls),
   or reuse the rule you already compiled (no AI call):

   ```bash
   python3 -m guardrailgen.simulation.stack activate "$(ls -t "$GG"/runs/compilation_*/rules/*.json | head -1)"
   ```

   Wait for `active`.
5. In **terminal 5**, start driving (Step 19):

   ```bash
   python3 -m guardrailgen.simulation.stack go 'Go to the goal.'
   ```

#### B. Full reset: close everything and start from zero

Use this if something looks stuck, Gazebo froze, or you are not sure which
programs are still running.

1. Press `Ctrl+C` in all five terminals and close them. Also close the Gazebo
   window.
2. Make sure nothing is left running. Open one Ubuntu terminal and paste:

   ```bash
   pkill -f chat_gpt_service; pkill -f my_robot_controller; pkill -f gzserver; pkill -f gzclient
   cd "$GG" && source scripts/stack_env.sh && python3 scripts/inspect_stack.py
   ```

   The last command should print **nothing** (meaning no leftover programs).
   If Gazebo still misbehaves, use the strongest reset: in **Windows
   PowerShell** run `wsl --shutdown`, wait 10 seconds, and open Ubuntu again.
   This closes all of Ubuntu, not only this project.
3. Start again from **Part B** (open five terminals, `source` line, Steps 12
   or 13, then Steps 14 to 19). Gazebo starts with the robot at the start
   position, so `reset_house.sh` is not needed.

Your earlier results in `runs/` are never deleted by either reset; every run
gets its own new folder.

#### Shut down when you are done

Press `Ctrl+C` in all five terminals and close them (and the Gazebo window).

---

## Part C (optional): Try your own rules without the robot

This only needs Steps 1, 7, 8 and 9. In one Ubuntu terminal:

```bash
cd "$GG"
set -a; source .env; set +a
bash scripts/run.sh compile 'Keep the magnitude of commanded linear speed at or below 0.2 m/s.' \
    --id my-first-rule --scenario config/turtlebot_development.json \
    --require-rtamt --report artifacts/last-compilation.json
```

Replace the sentence with your own rule. The program answers with one of:

- **compiled**: your rule was translated and passed the checks; the saved file
  appears in `artifacts/`.
- **clarification**: your sentence was ambiguous; rephrase it more precisely
  (include numbers and units, for example `0.2 m/s`).
- **unsupported**: the rule needs something not supported yet (for example
  time-based rules like "for 5 seconds" or "eventually").

Each compile makes 1 to 3 Groq calls. To test a rule on example numbers, see
`README.md` (command `check`).

---

## If something goes wrong

| Problem | Fix |
| --- | --- |
| `No such file or directory` for a `setup.bash` | A build step (Step 5, 6 or 11) did not finish. Re-run it and look for `Failed`. |
| `$GG` is empty / `cd: : No such file` | Redo Step 7, then open a new Ubuntu terminal. |
| Programs behave like "old" SafeLLMRA, or `package not found` | You forgot `cd "$GG" && source scripts/stack_env.sh` in that terminal. |
| Gazebo window never appears or is black | Wait 2 minutes. Run `wsl --update` in PowerShell, restart, try again. Close other heavy programs. |
| Robot never moves after Step 19 | Check Step 18 said `active`. Run `python3 -m guardrailgen.simulation.stack status`. Make sure only one of each terminal is running. |
| Robot stops halfway, around 180 s, or when it runs out of AI calls | Check `episode_seconds` in the run's `run_configuration.json`. If it says 180, terminal 4 was loaded before the time limit changed. Close terminals 2 to 4, open new ones, run the `source` line again, and raise the call limit (`export GUARDRAILGEN_MODEL_CALL_LIMIT=80`). The `Waiting for service /spawn_entity` line in terminal 1 is normal while Gazebo starts. |
| `rate limit` / `429` in terminal 2 | Groq is throttling you. Wait a few minutes; the robot waits and stays stopped meanwhile. |
| `403` or `401` errors | Your Groq key in `.env` is wrong or missing (Step 9). |
| Tests fail in Step 10 | Re-run Step 8, and make sure you used the **Ubuntu** terminal, not PowerShell. |
| Leftover programs from an earlier run | `python3 scripts/inspect_stack.py` lists them. Close their terminals, or restart Ubuntu with `wsl --shutdown` in PowerShell. |

## What the results do and do not mean

This is a research prototype for a bachelor's thesis. A run where the robot
avoids the kitchen shows that the pipeline worked in that run. It is **not** a
safety guarantee: the robot motion prediction is experimental, the "stop"
command is not verified braking, and the orange kitchen is a hand-placed test
zone. More details: `README.md`, `docs/four-terminal-setup.md`,
`docs/house-results.md`, `docs/implementation-status.md`.
