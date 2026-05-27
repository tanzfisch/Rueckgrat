Changelog
=========

0.4.1
-----

- #25 fixed misshanling of incomming messages

0.4.0
-----

- #38 generate new context for each new conversation
- #32 improved resource handling
- removed DEV_MODE again
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
- added script to deploy docker image to remote location
- some refactor across the board
- some improvements to image generation prompts

0.2.0
-----

- #3 image generation embedded in conversation
- #13 added common module to share code amongst applications
- #8 introduction of nested jobs processing user requests
- improved context generation to reduce size (#1)
- #19 reduced complexity in text classification
- improved promts for image, text and and context generation
- improved handling of image downloads
- improved bubbles layout for different aspect ratios of images
- added seed to llama.cpp interface
