Changelog
=========

0.7.0
-----

- #73 improving installer
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
