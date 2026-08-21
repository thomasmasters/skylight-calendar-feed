# Skylight calendar feed

This repository publishes a filtered Outlook iCalendar feed from
`docs/filtered-calendar.ics`. A scheduled GitHub Actions workflow refreshes the
file every 15 minutes and removes all `LOCATION` properties, including folded
continuation lines, before publishing it.

## Required repository setup

Create an Actions repository secret named `OUTLOOK_ICS_URL` containing the
private Outlook ICS subscription URL:

1. Open **Settings → Secrets and variables → Actions**.
2. Select **New repository secret**.
3. Name it `OUTLOOK_ICS_URL` and paste the Outlook calendar publishing URL.

After this pull request is merged and the secret is configured, run
**Actions → Refresh Skylight calendar feed → Run workflow** once to verify the
setup. Scheduled workflows run from the default branch; GitHub may occasionally
delay scheduled runs during periods of high load.

The Outlook subscription URL must remain secret. Do not commit it to this
repository or paste it into workflow logs.
