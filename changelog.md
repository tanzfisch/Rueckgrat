Changelog
=========

0.32.0
------

- #230 rethinking agents
-     redesigned the agent job worker loop, tasks and companion passes use the same worker framework as agent jobs
-     removed the run_code tool, code runs through spawn_job and bash
-     simple job loop: goal, check and folder decided at the start, one worker per step, only the step's check decides (run in a clean shell in the job's folder), a failed check gets one retry told what failed, then the job fails
-     own sandbox layer instead of llm-sandbox (removed, docker SDK added as hub dependency)
-     one long-lived sandbox container per contact on python:3.11-trixie, with passwordless sudo: sudo apt-get install works and stays while the container lives
-     sandboxes run in gVisor (runsc, HUB_SANDBOX_RUNTIME), the installer installs and registers it with Docker, without it the hub falls back to runc with a warning
-     gVisor is registered with --allow-suid so sudo works in the sandboxes, the installer adds it to an existing runsc registration, the hub warns when it is missing
-     packages installed with sudo apt are recorded and installed again when a container is made for a new image
-     the contact's files are backed up before every agent job worker that changes files, size limit HUB_SANDBOX_BACKUP_MAX_MB (default no limit)
-     new reset_sandbox tool: a fresh container from the clean image with the files kept, on request the files back to the last backup
-     idle sandbox containers are stopped after 24 hours (HUB_SANDBOX_IDLE_MINUTES), the next command starts them again
-     limits of 2 CPUs, 2 GB memory and 256 processes, the uninstall script removes sandboxes and backups
-     the task tool only takes over from spawn_job when the message says when to act (in 2 hours, every day, tomorrow, at 7pm), a build request with "tell me when it works" starts a job
-     task passes see the real state of the contact's background jobs and do not start a job just to check one
-     laya dataset: build requests from a sandbox test that must start a job
-     job workers get 40 calls (HUB_JOB_WORKER_CALLS) and end on finish or when their calls or time are used up, the check decides the rest
-     one folder per job, chosen at the start: a new project, a listed project the job names, for work on files the conversation's project, else the conversation's workdir, workers start in it
-     the job delivers the files (those it names, else the changed files without build output), a failed job sends what it made, reports never claim files that are not attached
-     a failed job's report says which step failed and why (the check and its output) and never promises to retry
-     workers know how long a reply can be (from the llm's context), short worker, plan and report prompts, no review, merge or retry llm calls
-     job workers always get the shell and file tools, the user's messages during a job go to its next step

0.31.0
------

- #193 webdav for colaborative access to the files an AI is working on
- #225 SMB for colaborative access to the files an AI is working on
- #226 allow companions to share files
- #227 fixing error handling in agent jobs

0.30.0
------

- #215 unify protocols for jobs, tasks and companions
- #220 added uninstall script
- #167 companion greeting handling
- #222 offline websearch, wikipedia and maps with an optional Project NOMAD in the LAN
-     installer asks for the NOMAD url, hub manager offline nomad changes or clears it later, no restart
-     wikipedia and websearch fall back to NOMAD's kiwix library without internet, websearch searches all books of the language
-     book list is read live from kiwix, the hub keeps no copy
-     show_map draws offline tiles in the hub from NOMAD's pmtiles, places are found by their wikipedia coordinates, a tap opens NOMAD's map
-     fetch_url is always available, without internet it still reads pages in the LAN, NOMAD and kiwix are allowed automatically
-     convert works offline, currency rates are saved once a day and fetched on the first hub start
-     hub manager offline simulate on|off acts as if there were no internet, offline status shows NOMAD, its library and map
-     new capabilities library and offline_map, shown in the chat's status
-     added pmtiles, mapbox-vector-tile and Pillow hub dependencies
- fixed offline library links with special characters in their path (encoded twice)
- websearch always searches NOMAD's library next to the web, the best answers of both make the result
- copy buttons on every text block of a bubble (text, code, quotes, tables tab separated) and in the text preview
- a copy button for the whole reply under the assistant's bubble, also without sources
- block copy buttons are small and sit in the top right corner, one line messages keep their height
- fixed quote blocks breaking the rendering of their bubble
- the yellow connection bar is semi transparent and lets clicks through
- show_map is picked for questions where a place is, e.g. "where is the pyramid of giza?" or "Where's Wellington"
- offline map labels use the English name, else the local one in the Noto font of its script (Cyrillic, Greek, Arabic, Hebrew, Thai, Devanagari, CJK), nothing drawn as boxes
- offline map tiles drawn by the last hub are cleared on hub start
- added Noto fonts (~135 MB) to the hub image and the fonttools hub dependency

0.29.0
------

- #170 added task tool which creates repeating or one of tasks in the background 
- #197 added tts tool which turns text in to speech for the user to donwload
- #212 added join_files tool which joins text or audio files into one file, for jobs and tasks only
- #209 improved writing files to the sandbox
-     write_file and text_to_speech take a full path, e.g. a project folder
-     write_file only writes text, audio, image and archive files are refused
-     an existing file is only replaced with the overwrite flag
-     text_to_speech writes mp3, ogg or wav
-     job steps pass the paths of their saved files on to the next steps
-     websearch answers are part of the tool results
-     a bash ls of the work folder counts as grounded
-     tools mark themselves as fixable instead of the FIX_TOOLS list, problems keep their tool's name
-     a worker fails when its file tools still fail after the fix rounds
-     tools don't name other tools, the planner and tool setup explain how they work together
-     planner talks about works made of parts instead of audiobooks
-     agent jobs run up to 8 h, tasks and companion passes up to 90 min, job llm calls up to 30 min
-     tts timeout by priority: 4 min for chat, background requests wait as long as their job
-     tts node queues speech requests: chat first, requests of gone clients are skipped, a full queue answers busy and background requests retry
-     improved text_to_speech laya question, mandatory threshold 0.75
-     docs: communication.md describes how chat, hub and nodes talk, CONTRIBUTING.md renamed to DEVELOPMENT.md
- #216 added default backstory to character creation
- #211 explorer button in conversations list
- #213 copy path button on files in file explorer
- #210 play button for audio files in contact fs
- #218 added option to override voice for ai tools
- #217 improved tts quality by using longer chungs for agent jobs and caching voice samples

0.28.1
------

- #208 fixing round
-     replies go to the chat session that asked for them, status messages only show in their conversation
-     fixed laya tune.sh
-     fixed old tool results leaking into later replies: a new seed per reply
-     device timezone is the default when the user has none set
-     downloads and tts voices are limited to their owner
-     empty transcripts are removed
-     fixed typos
-     tasks expose their route through getters only
-     removed db compatibility code for old versions
-     new users land on the profile wizard again after their first login
-     a failed tool call no longer stops the following tool rounds
-     current_time and date_calc use the user's time zone when none or "local" is given
-     the profile wizard only saves a time zone the user changed, settings can switch back to the device time zone
-     contact conversations of other users return 404
-     generated images are stored with their real file size
-     improved laya tool questions and thresholds, more laya training data

0.28.0
------

- #192 reduce user profile to minimum
- #207 add user id to logs in hub
- #191 prevent android disconnect when in backgrond
- #206 settled bash vs write_file conflict by introducing share_file and let write file only write to agent fs
- #205 added profile picture for user
- #198 added transcribe app
- #194 improve handling of missing services

0.27.0
------

- #176 ordering tool calls: laya-detected tools one at a time, then one optional request for the rest
-     fetch_url is selected by a url in the message, not by laya
- maps don't try to simulate dark mode anymore. it was too ugly
- #175 the assistant can attach text files: one file as itself, several files of one message as a single zip
- #109 cleanup round after too heavy AI use
- #181 start audio playback while still streaming text answer
- #177 removed scenario cration for faster response to first message
- #162 agents are allowed to use the image generation
- #180 refactored prompts
- #183 expose more companion settings to the ui
- #184 bash tool
- #186 file browser for conversation files
- agents have access to their own sandbox file system to work on projects
- #187 added price finder tool
- preview of text files in chat without downloading
- added tools to tune laya tool detection
- #189 AI can ask actively for tools to use

0.26.0
------

- #156 added code execution tool using llm-sandbox
- #172 auto code fencing
- #173 added copy button to code blocks in chat
- #174 agent protocols for better insight of the work of agents

0.25.0
------

- #125 added polling tool
- #158 refactored companion code to run now as AgentJob
- #165 added persistent companion option to wizzard
- #160 fixed issue with voice id exporting contacts
- #168 save / load compation flag for ocntacts
- #166 ask user for settings after first login
- #159 display maps of addresses in chat when the AI thinks it helps the context

0.24.0
------

- #151 shut off thinking step for thinking models
- #152 introducing agents
- #153 added credits and licenses to chat app
- #154 added wallpaper to login screen
- #7 light and dark mode switch

0.23.0
------

- #146 patching security issues
      installer: no sudo password handling (ssh keys or ssh/sudo prompt themselves), -p removed, host keys pinned (accept-new)
      installer: asks for each machine's sudo password once at the start, temporary sudoers rule removed on exit
      revocable refresh tokens (hashed, rotated, logout and password change revoke), log in once after the update
      web fetches pinned to the checked address, redirects checked, HUB_FETCH_ALLOW for local pages
      client config file only readable by its owner
      create_rueckgrat_user.sh sets up a separate install user (ssh key, passwordless sudo) on all machines, use with install.sh -u
      README explains which users, sudo rights and ssh keys the installer needs
- #121 fixed display of source URLs. now part of the chat bubble
- #147 nightly maintenance: conversation summaries with vectors to find old conversations by meaning
- #149 improve conversations: supressing made-up facts, sources or shared memories, lasting user facts kept in the context, fewer *actions* and questions
- #150 stability pass
      image downloads: failed single attempts only logged at debug, one error once all retries gave up
      image downloads: two downloads of the same file no longer share one .part file (FileNotFoundError on rename)
      edit profile from the settings goes back to the settings (was the contact list), also after save
      translate page follows the "Enter sends" setting like the chat (Enter always made a new line)
      gallery dates shown in local time (were UTC, images from the morning showed the day before)
      chat mic: if the mic can't start (no audio device) the button goes back to off instead of an unhandled traceback
      chat input has the keyboard focus on opening a conversation also with "Enter sends" on (flet's focus() missed shift_enter fields)
      no more flet deprecation warnings: text field and dropdown borders use border=OutlineInputBorder (field_border in theme.py), NoInputBorder instead of InputBorder.NONE
- #18 page navigation with a back stack: back (header, Android, browser) returns to the page you came from, login and contacts start the stack anew
- #148 installer installs all hosts at the same time (copies first, then one log per host in logs/install-<host>.log)

0.22.0
------

- #139 faster replies by optimizing meta job
      using Laya to detect tool usage where possible
      improved websearch now using headless browser
      cach tts data for faster replay
      improved conversation context now focuses on open questions and decisions
- #140 fixed text bubble selection color
- #136 user can delete individual memories
- #124 added galllery containing all pictures of the user account
- #142 fixed slow load of chat page
- #143 uploading images for profile images
- #111 stay logged in on android until user explicitly loggs out
- #37 persistent companion: plans its own day every night (private calendar), writes first now and then

0.21.1
------

- #137 audio recording unpause after speech playback

0.21.0
------

- #129 adding default assistant and more image styles
- #12 save and search memories per contact using fastembed
- #135 bruished up tool definitions
- #122 added notifications for incomming messages and images

0.20.0
------

- #53 contact images use the contact's current profile image as face reference (IP-Adapter FaceID PlusV2, sdxl)
- #108 added voice samples
- #100 allow user to change email and password
- #110 cleanup chat ui
- #113 ability to talk over ai and interrupt it's processing
- tts now in chunks to improve latency
- #112 buffer stt in chat client to manage disconnects mid speach
- #115 added translator tool
- #116 added save and share buttons to image widget
- #117 added image tool
- #119 fixed apk build version
- #126 fixed mic not recording during locked screen on android
- #128 improved integration of nsfw image gen

0.19.0
------

- #72 added option to build chat apk using the install.sh script
- #103 fixed cert issue
- #102 seperating user name (login) from user character name
- #104 using multilingual chatterbox now by default
- #106 hardenig image generation. trying to prevent double generation
- #105 async image gen
- #38 deleting a conversation or contact removes related images from the hub and the client cache

0.18.0
------

- #84 auto install of models on demand for stt, tts and image gen
- #15 added conversion tool
- #59 tool index as first step to nested tooling
      new tools: calculator, current time, date calc, wikipedia, weather, url fetcher
- install.sh and dev.sh improvements
- fixed issue with hw detection durign install
- added missing image style in character edit form
- diffuser dependency was missing on tts only nodes
- fixed truncated prompt issue during image generation
- #94 improved hub management
- #95 added cloudflare tunnel option to installer
- #96 hide users from other users in invite mode
- #98 added default users selection during install

0.17.0
------

- #90 fixed character images not showing in web mode (flet run --web)
- #91 added invite based signup
- #33 ports are now configureable for hub, node and llama.cpp
- #92 adding more default voices
- #93 auto regen missing images

0.16.0
------

- #75 moving faster whisper from hub to node
- #87 using android back button
- #66 storing image gen prompt when generating images for later use
- #46 added mute button to chat
- #89 fixed issue with websearch
- #88 animate mute button when generating tts
- #69 improve robustness of chat stream

0.15.0
------

- #11 text to speech moved from client side piper to chatterbox running as a node service
- #81 animation in ui when speaking user detected
- #82 fixed speech playback on android, wav is played in app with flet-audio instead of aplay
      speech runs in page.run_thread so the player connects to the page, player released after playback, added flet-audio 1.0.4 dependency
- #80 allow user to upload voice samples for characters
- #62 simplified character generation ui and backend
- #83 improved character editing

0.14.1
------

- #68 fixed colored emojies

0.14.0
------

- #76 configurable models path (during installation)
- #44 made log level configurable for client
      allows to change log level across the whole system at runtime see /log-level/{level}
- #78 more flexible llama config per model in registry.json
      faster reinstalls
- #73 hub and nodes can start in any order and reconnect automatically after a connection loss

0.13.0
------

- #70 loading faster whisper from disk instead of downloading it each start of hub
- #64 removed chat via docker support
- #74 made hub able to install models without being a node

0.12.0
------

- #55 switchoing from PySide to flutter for better mobile support

0.11.4
------

- #60 moved model download out of ui process to prevent hang

0.11.3
------

- #61 fixed crash in TTS

0.11.2
------

- #58 fixed health check timout issue

0.11.1
------

- #57 fixed wrong path when calling TTS and added missing piper model

0.11.0
------

- #52 cleanup model registry
- #10 added speech to text using silero_vad and faster_whisper

0.10.0
------

- #36 replaced ComfyUI with directly using diffusers (see ImageGen)
- #49 fixed issues when running on different hardware. generally amd and nvidia are supported. Intel is not since I don't have intel GPUs
- #50 replaced .env.example with code writing .env directly
- #54 fixed issue where we run out of vram during image generation

0.9.1
-----

- #42 fixed speech playback in standalone chat

0.9.0
-----

- #40 improving installer
  - cleaned up issue with Removing previous Rueckgrat installation during installation
- #25 streaming for finalized answer

0.8.0
-----

- #32 largely rewritten the installer. now allows multi host installation
- #31 fixed audio

0.7.1
-----

- fixed some issues with the installer

0.7.0
-----

- #73 improving installer
- #5 improving installer some more
- #75 docker for chat
  known issues: autostart fails, no audio output
- #72 fixed bug where file open dialog oppened twice

0.6.1
-----

- #26 improving installation

0.6.0
-----

- #57 added sync download for DownloadQueue
- #56 improved model download
- #49 replace llama.cpp service with docker model runner
- #62 rethinking tools, skills and jobs
- #6  added websearch tool
- fixed issue with loading animation in Image class
- #42 added status/progress updates to ui
- #65 prompt user for server config on first startup
- made chat client run on windows

0.5.0
-----

- #43 introducing user profile data
- #48 added simple progress page after contact gen
- #31 refactored endpoints
- #55 fixed download logic after endpoints change
- #58 auto remove formatting when pasting text
- added handling of thinking responses

0.4.1
-----

- #25 fixed misshanling of incomming messages

0.4.0
-----

- #38 generate new context for each new conversation
- #32 improved resource handling
removed DEV_MODE again
- #17 working on discovery and decided to stick with simple config file
- #22 added image overlay
- #41 improve context update for better consistency, each new conversation begins with a randomized context
- #24 added character creation wizzard
- #39 refactor download handling and added image cache clean up worker

0.3.0
-----

- #35 added DEV_MODE. Set to mockup for easier development
- #36 added RueckgratConfig for certralized config handling
- #37 added code workspace
- #5  added settings menu for client
- #28 improved some of the existing contact templates
added script to deploy docker image to remote location
some refactor across the board
some improvements to image generation prompts

0.2.0
-----

- #3 image generation embedded in conversation
- #13 added common module to share code amongst applications
- #8 introduction of nested jobs processing user requests
improved context generation to reduce size (- #1)
- #19 reduced complexity in text classification
improved promts for image, text and and context generation
improved handling of image downloads
improved bubbles layout for different aspect ratios of images
added seed to llama.cpp interface
