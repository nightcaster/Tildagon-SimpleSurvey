# Simple Survey - Tildagon App

A MicroPython application for the EMF Camp Tildagon badge that allows users to create, run, and display results of custom button-polled surveys.

## Features

- **Create Surveys:** Setup survey names, questions, and up to 6 options with custom text labels, button assignments, and LED colors.
- **Run Polling:** Collect responses by selecting a survey. The question screen is displayed first, then options are shown with adjacent button-lit LEDs to prompt voters.
- **Circular Results Gauge:** Displays percentages of votes in a sleek circular segments chart (donut style) resembling a speedometer, color-coded by option.
- **LED Indicators:** Uses the 12 front LEDs next to the buttons to guide the user on which buttons map to which options, and flashes all LEDs in the option's color upon a successful vote.
- **Persistent Storage:** All surveys and vote results are persisted in a local `surveys.json` file.

## Button Mapping & LEDs

The 6 buttons around the hexagon are mapped to their adjacent pairs of front LEDs (indices 1 to 12):

| Button | Logical Action / Option | LED Indices |
|--------|-------------------------|-------------|
| **1**  | `UP` (Button A)         | 12 & 1      |
| **2**  | `RIGHT` (Button B)      | 2 & 3       |
| **3**  | `CONFIRM` (Button C)    | 4 & 5       |
| **4**  | `DOWN` (Button D)       | 6 & 7       |
| **5**  | `LEFT` (Button E)       | 8 & 9       |
| **6**  | `CANCEL` (Button F)     | 10 & 11     |

## Configuration

The application uses standard metadata files:
- **`tildagon.toml`**: Metadata configuration for publishing on the Tildagon App Store.
- **`metadata.json`**: Metadata configuration for local simulation/development.

## Installation

Clone this repository into the `/apps/` directory of your Tildagon badge:
```bash
git clone https://forge.nightcaster.duckdns.org/nightcaster/Tildagon-SimpleSurvey.git /apps/simplesurvey
```
Or copy files over using `mpremote`:
```bash
mpremote fs cp app.py :apps/simplesurvey/app.py
mpremote fs cp surveys.json :apps/simplesurvey/surveys.json
mpremote fs cp tildagon.toml :apps/simplesurvey/tildagon.toml
```

## License

This project is licensed under the LGPL-3.0-only License.
