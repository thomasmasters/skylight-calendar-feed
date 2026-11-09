# Skylight calendar feed

GitHub Pages publishes `docs/filtered-calendar.ics`. An hourly GitHub Actions
workflow rebuilds it from a private Outlook ICS feed.

## One-time setup

In **Settings → Secrets and variables → Actions**, create a repository secret
named `OUTLOOK_ICS_URL` containing the Outlook calendar's private ICS URL.
Never commit that URL to the repository.

After adding the secret, open **Actions → Refresh calendar feed → Run workflow**
once. The workflow will then run hourly at 17 minutes past the hour.

## Filtering behaviour

The generator:

- includes only `Personal`, `Other`, and `Orange Category` events;
- removes every event location;
- converts timed events to `Europe/London`;
- preserves Outlook's exclusive `DTEND` for all-day events, including multi-day
  events;
- keeps stable public event IDs so calendar clients update rather than duplicate
  events; and
- refuses to publish an empty or unexpectedly truncated calendar.

To change the category allow-list later, set the workflow environment variable
`ALLOWED_CATEGORIES` to a comma-separated list.
