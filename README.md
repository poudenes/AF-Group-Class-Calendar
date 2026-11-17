# Anytime Fitness Group Lessons voor Home Assistant

Zet het groepslesrooster van je Anytime Fitness-club als kalender in Home Assistant:
**`calendar.anytime_fitness_group_lessons`** ("Anytime Fitness group lessons").

Het rooster staat op de clubsite alleen als plaatje (knop **Bekijk het rooster**, bv. op
[afzuidas.nl](https://afzuidas.nl/#groepslessen)). De integratie:

1. haalt **elke dag** de clubpagina op en zoekt daarin het roosterplaatje;
2. vergelijkt het plaatje (SHA-256) met dat van de vorige keer;
3. **zelfde plaatje → niets doen**, de kalender blijft zoals hij is;
4. **ander plaatje → uitlezen** met een AI Task-entiteit (vision-model) en de kalender bijwerken.

De lessen zijn een weekrooster: elke les komt elke week terug op dezelfde dag en tijd.
Bij een nieuw rooster blijven de dagen ervóór het oude rooster houden; het nieuwe geldt vanaf
vandaag (of vanaf de startdatum van de periode als die nog moet komen).
Bevat het nieuwe plaatje dezelfde lessen, dan verandert er niets.

Per les in de kalender:

| Veld | Voorbeeld |
|---|---|
| titel | `Fit 60+` |
| tijd | di 10:30 – 11:30 |
| locatie | `Park – Ontmoetingseiland Gijsbrecht van Aemstelpark` (of `Studio`, `Funx Zone`) |
| omschrijving | `Trainer: Celestino` / `Zaal: *Park` / extra info zoals `30 min` |

## Benodigd: een AI Task-entiteit

Home Assistant kan zelf geen tekst uit plaatjes lezen. Daarvoor gebruikt deze integratie
**AI Task** (Home Assistant 2025.8+). Stel eerst een integratie in die een AI Task-entiteit met
beeldherkenning levert, bv. **Google Gemini**, **OpenAI**, **Anthropic** of **Ollama** met een
vision-model. Het AI-model wordt alleen aangeroepen als het plaatje echt veranderd is
(ongeveer eens per maand), dus de kosten zijn verwaarloosbaar.

## Installatie via HACS

1. HACS → menu (⋮) → **Custom repositories**
   - Repository: `https://github.com/poudenes/AF-Group-Class-Calendar`
   - Type: **Integration**
2. Zoek **Anytime Fitness Group Lessons**, installeer en **herstart Home Assistant**.
3. Instellingen → Apparaten & diensten → **Integratie toevoegen** → *Anytime Fitness Group Lessons*.
4. Vul de website van je club in (standaard `https://afzuidas.nl/`) en kies de AI Task-entiteit
   (leeg = de standaard AI Task-entiteit uit Instellingen → Systeem → Algemeen).

Handmatig kan ook: kopieer `custom_components/af_group_classes` naar `config/custom_components/`
en herstart.

Instellingen later wijzigen: bij de integratie → ⋮ → **Opnieuw configureren**.

## Actie `af_group_classes.refresh`

Controleer nu meteen in plaats van te wachten op de dagelijkse controle.

```yaml
action: af_group_classes.refresh
data:
  force: true            # optioneel: ook opnieuw uitlezen als het plaatje niet veranderd is
  # image_path: /config/www/rooster.jpg   # optioneel: lokaal plaatje i.p.v. de website
```

`force: true` is handig als het AI-model iets verkeerd heeft gelezen (bv. na het wisselen van model).

## Als de website Home Assistant blokkeert

De clubsite draait achter Cloudflare. Weigert die het verzoek van Home Assistant (HTTP 403), dan
krijg je een melding onder **Instellingen → Reparaties** en blijft de kalender het laatst
gelezen rooster tonen. Je kunt het plaatje dan zelf aanleveren:

1. Sla het roosterplaatje op als bv. `/config/www/rooster.jpg`.
2. Zet in `configuration.yaml`:
   ```yaml
   homeassistant:
     allowlist_external_dirs:
       - /config/www
   ```
3. Voer de actie uit met `image_path: /config/www/rooster.jpg`.

## Attributen van de kalender

| Attribuut | Betekenis |
|---|---|
| `period` | periode op het rooster, bv. `Okt 2026` |
| `schedule_image` | URL van het uitgelezen plaatje |
| `classes_per_week` | aantal lessen per week |
| `last_checked` | laatste dagelijkse controle |
| `last_changed` | laatste keer dat de lessen veranderden |

Het laatst uitgelezen plaatje staat ook in de **Mediabrowser** onder *Anytime Fitness group lessons*.

## Ontwikkelen

```
pip install pytest-homeassistant-custom-component
pip install $(python script/test_requirements.py)
python -m pytest
```

## Nieuwe versie uitbrengen

1. Verhoog `version` in `custom_components/af_group_classes/manifest.json`.
2. Commit en push.
3. Maak een GitHub-release met tag `v1.0.1` (enz.). HACS ziet die release als update.
