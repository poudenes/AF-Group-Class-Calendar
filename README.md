# Anytime Fitness Group Lessons for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Validate](https://github.com/poudenes/AF-Group-Class-Calendar/actions/workflows/validate.yml/badge.svg)](https://github.com/poudenes/AF-Group-Class-Calendar/actions/workflows/validate.yml)

Turn the group class schedule of your Anytime Fitness club into a Home Assistant calendar:
**`calendar.anytime_fitness_group_lessons`** ("Anytime Fitness group lessons").

Many Anytime Fitness clubs only publish their group class schedule as an **image** (for example
behind the *"Bekijk het rooster"* button on [afzuidas.nl](https://afzuidas.nl/#groepslessen)).
This integration reads that image with an AI model that understands images, and turns every class
into a weekly recurring calendar event. You can show it on a dashboard, use it in automations
("remind me 1 hour before Yoga"), or just look at it in the Calendar panel.

> This is an unofficial community project. It is not affiliated with or endorsed by
> Anytime Fitness.

## How it works

1. **Once a day** the integration looks at the schedule image: either on the club website, or the
   newest image you uploaded to a media folder in Home Assistant (see [Sources](#sources)).
2. It compares the image with the one it read last time (SHA-256 hash).
3. **Same image → nothing happens.** The calendar is left alone and no AI call is made.
4. **New image → it is read** by your AI Task entity and the calendar is updated.

The schedule is a weekly timetable: each class repeats every week on the same day and time.
When a new schedule appears, the days before it keep the old schedule (so past weeks stay correct)
and the new one applies from today, or from the first day of its period if that is still to come.
If a new image contains exactly the same classes, the calendar does not change.

Each calendar event contains:

| Field | Example |
|---|---|
| Title | `Fit 60+` |
| Time | Tue 10:30 – 11:30 |
| Location | `Studio`, `Funx Zone`, or a footnote such as `Park – Ontmoetingseiland Gijsbrecht van Aemstelpark` |
| Description | `Instructor: Celestino` / `Room: *Park` / extra info such as `30 min` |

## Requirements

- **Home Assistant 2025.8 or newer.**
- **An AI Task entity that can read images.** Home Assistant cannot read text from images by
  itself, so the integration uses Home Assistant's built-in
  [AI Task](https://www.home-assistant.io/integrations/ai_task/) feature. Any integration that
  provides an AI Task entity with image (attachment) support works, for example:
  - [Google Generative AI](https://www.home-assistant.io/integrations/google_generative_ai_conversation/) (Gemini): has a free tier, tested with this integration
  - [OpenAI](https://www.home-assistant.io/integrations/openai_conversation/)
  - [Anthropic](https://www.home-assistant.io/integrations/anthropic/) (Claude): needs an API key; a Claude.ai subscription cannot be used
  - [Ollama](https://www.home-assistant.io/integrations/ollama/) with a vision model, if you want to run it locally

  The AI is only called when the schedule image actually changed (typically once a month), so
  costs are negligible.

## Installation

### HACS (recommended)

1. In HACS, open the menu (⋮) → **Custom repositories**.
   - Repository: `https://github.com/poudenes/AF-Group-Class-Calendar`
   - Type: **Integration**
2. Search for **Anytime Fitness Group Lessons**, install it and **restart Home Assistant**.

### Manual

Copy `custom_components/af_group_classes` into your `config/custom_components/` folder and
restart Home Assistant.

## Configuration

**Settings → Devices & services → Add integration → Anytime Fitness Group Lessons.**

| Option | Description |
|---|---|
| **Source** | **Club website** or **Media folder** (see below). |
| **Club website** | Only for the website source: the page of your club that contains the schedule image, e.g. `https://afzuidas.nl/`. |
| **AI Task entity** | The entity that reads the image. Leave empty to use the default AI Task entity set in Home Assistant. |

You can change these later via the integration → ⋮ → **Reconfigure**. Switching source keeps the
calendar and the schedules that were already read.

## Sources

### Club website

The integration downloads the club page, finds the schedule image on it (an image whose file name
or description mentions *rooster*, *schedule* or *timetable*) and downloads it.

**Some club websites block Home Assistant.** For example, afzuidas.nl sits behind Cloudflare and
answers requests from Home Assistant with **HTTP 403**. The integration deliberately does not
pretend to be a web browser to get around that. If the website blocks Home Assistant:

- when adding the integration you get *"The website blocks Home Assistant (HTTP 403)"*. Choose
  **Media folder** instead;
- on an existing entry you get a notice under **Settings → Repairs**, and the calendar keeps
  showing the last schedule it read.

### Media folder

You upload the schedule image yourself. This always works, whichever website your club uses.

1. Choose the source **Media folder**. The integration creates the folder **Anytime Fitness** in
   your local media (`/media/Anytime Fitness` on Home Assistant OS).
2. Save the schedule image from your club's website in your web browser (open the schedule and
   use *Save image as…*). JPEG, PNG and WebP are supported.
3. In Home Assistant open **Media → My media → Anytime Fitness**, click **Manage** (top right)
   and upload the image. This also works from the mobile app.
4. Within a day the integration reads it. To do it right away, run the action
   `af_group_classes.refresh` (see below).

When your club publishes a new schedule, just upload the new image. The **most recently changed**
image in the folder is used, whatever its file name. Uploading the same image again does nothing.

You can also put the file there via the Samba share, File editor or Studio Code Server add-ons.

## Action `af_group_classes.refresh`

Check for a new schedule now instead of waiting for the daily check.

```yaml
action: af_group_classes.refresh
data:
  force: true                            # optional: read the image again even if it did not change
  # config_entry_id: ...                 # optional: only this entry (default: all)
  # image_path: /media/my-schedule.jpg   # optional: read this local file once instead
```

`force: true` is useful when the AI misread something, for example after switching to another
AI model. `image_path` must be inside a folder listed in `allowlist_external_dirs` (your media
folders are allowed by default).

## Calendar attributes

| Attribute | Meaning |
|---|---|
| `period` | Period printed on the schedule, e.g. `Okt 2026` |
| `schedule_image` | The image that was read (URL or file) |
| `classes_per_week` | Number of classes per week |
| `last_checked` | Time of the last daily check |
| `last_changed` | Last time the classes changed |

The last image that was read is also visible in the **Media** panel under
*Anytime Fitness group lessons*.

## Example automation

Get a notification one hour before every Yoga class:

```yaml
automation:
  - alias: "Yoga reminder"
    triggers:
      - trigger: calendar
        event: start
        entity_id: calendar.anytime_fitness_group_lessons
        offset: "-1:00:00"
    conditions:
      - condition: template
        value_template: "{{ 'yoga' in trigger.calendar_event.summary | lower }}"
    actions:
      - action: notify.notify
        data:
          title: "{{ trigger.calendar_event.summary }} in 1 hour"
          message: >-
            {{ trigger.calendar_event.start[11:16] }} – {{ trigger.calendar_event.location }}
            {{ trigger.calendar_event.description }}
```

## Troubleshooting

| Problem | Solution |
|---|---|
| *"AI task failed: … 503 … high demand"* | The AI service was temporarily overloaded. Run `af_group_classes.refresh` again after a few minutes. Nothing is lost: an image that failed is retried at the next check. |
| *"No schedule image yet: upload it in Media → My media → Anytime Fitness"* | The media folder is empty; upload the schedule image. |
| *"The website blocks Home Assistant (HTTP 403)"* | Use the **Media folder** source. |
| *"No schedule image was found on this page"* | Use the page that actually shows the schedule, or the **Media folder** source. |
| Classes are missing or wrong | Run `refresh` with `force: true`, or try a stronger AI model. You can test your AI entity with the `ai_task.generate_data` action and the image as attachment. |

For more detail, enable debug logging:

```yaml
logger:
  logs:
    custom_components.af_group_classes: debug
```

## Development

```bash
pip install pytest-homeassistant-custom-component
pip install $(python script/test_requirements.py)
python -m pytest
```

## Releasing a new version

1. Bump `version` in `custom_components/af_group_classes/manifest.json`.
2. Commit and push.
3. Create a GitHub release with tag `vX.Y.Z`. HACS offers it as an update.

## License

[MIT](LICENSE)
