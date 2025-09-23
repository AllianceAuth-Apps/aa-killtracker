# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased] - yyyy-mm-dd

## [0.17.0] - 2025-09-23

### Update Notes

#### Changed periodic task schedule

Please update the value for `'schedule'` of Killtracker's periodic task in your local settings.
This change will help reduce peak load on CCP's servers.

The new default configuration looks like this:

```python
CELERYBEAT_SCHEDULE['killtracker_run_killtracker'] = {
    'task': 'killtracker.tasks.run_killtracker',
    'schedule': 60,
}
```

Please make sure to restart your AA instance so the changes can take effect.

>**Note**:<br>Killtracker will generate a Django warning until this important configuration change has been completed.

#### New rate limit

In case you have adjusted the settings `KILLTRACKER_MAX_KILLMAILS_PER_RUN` please note that the default hast been reduced to `100` in order to stay well below the rate limit. Please adjust your setting to make sure you stay well below the new maximum of 2 requests per second.

### Changed

- Comply with new CloudFlare rate limit of 2 API requests per second (see also [ZKB Readme - Limitations](https://github.com/zKillboard/RedisQ/blob/master/README.md#limitations))
- The previous cron based schedule for periodic tasks has been deprecated and replaces with a basic schedule.

## [0.16.0] - 2025-05-24

>**IMPORTANT**: When updating from a version prior to 0.13.0, please see the important update notes for 0.13.0 first!

### Changed

- Update ZKB_REDISQ_URL to new endpoint (!22) - Thank you @Dusty-Meg for the contribution!
- Updated tox tests to confirm with AA4 checks

## [0.15.0] - 2024-07-04

>**IMPORTANT**: When updating from a version prior to 0.13.0, please see the important update notes for 0.13.0 first!

### Added

- Ability to filter killmails by faction (#52)

### Changed

- Reorganized sections on the admin page for trackers: All attacker clauses and all victim clauses are now in their own new respective section
- Improved test suite

## [0.14.0] - 2023-11-27

>**IMPORTANT**: When updating from a version prior to 0.13.0, please see the important update notes for 0.13.0 first!

### Added

- Add support for AA4

## [0.13.0] - 2023-11-23

### Update notes

With a recent change to the zKillboard API the queue ID is now mandatory. Please add your queue ID via the new setting `KILLTRACKER_QUEUE_ID` in your local settings.

Please note that the queue ID must be globally unique for all users of the zKillboard API, so choose carefully.

We suggest to use your alliance name or alliance tag (without any spaces and special characters) as queue ID.

We recommend using only characters (upper and lower case) and numbers,
but no spaces or any special characters when choosing your ID.

Example (don't use this exact example):

```Python
KILLTRACKER_QUEUE_ID = "Voltron9000"
```

If you are running multiple instances of Killtracker please choose a different queue ID for each of them.

### Changed

- Added the ability to define a queue ID via the new mandatory setting `KILLTRACKER_QUEUE_ID`.

## [0.12.1] - 2023-10-05

### Changed

- Improve performance of tracker form page
- Remove NPC button from page with tracker form
- Refactoring

## [0.12.0] - 2023-09-11

### Update notes

Since we have added more types we recommend to re-run the load_eve command to ensure that all of the new types are available when creating a new tracker:

```sh
python manage.py killtracker_load_eve
```

### Added

- Add deployable to victim ship groups and types (#41)
- Add attacker weapon groups and types (#39)

## [0.11.0] - 2023-09-06

### Changed

- Added pylint checks
- Refactor to fix pylint issues
- Refactor to fix type issues
- Other code improvements

## [0.10.0] - 2023-07-11

### Changed

- Migrated to AA3 (incl. dropping support for AA2)
- Migrate to PEP 621 build process
- Added support for Python 3.11
- Removed local swagger spec file
- Updated dependencies

### Fixed

- Processing of killmail fails when ESI route endpoints returns error

## [0.9.2] - 2022-10-17

>**Update notes**: If you are upgrading from a version prior to 0.8.x, you please need to upgrade to 0.8.1 first to avoid any migration issues.

### Fixed

- webhook colors broke (#35)
- Error when trying to run tracker for killmail on admin site

## [0.9.1] - 2022-10-14

>**Update notes**: If you are upgrading from a version prior to 0.8.x, you please need to upgrade to 0.8.1 first to avoid any migration issues.

### Changed

- Store new killmails in temporary storage instead of passing them directly to tasks

## [0.9.0] - 2022-10-12

>**Update notes**: If you are upgrading from a version prior to 0.8.x, you please need to upgrade to 0.8.1 first to avoid any migration issues.

### Changed

- Improved database structure of killmails for better performance
- Consolidated migrations
- Removed support for Python 3.7
- Added support for Python 3.10

## [0.8.1] - 2022-09-21

### Fixed

- Removed link to squashed and removed migrations

## [0.8.0] - 2022-09-21

### Changed

- Removed outdated migrations from before the squash

### Fixed

- Victim alliance logo in Discord message (!10)

## [0.7.5] - 2022-09-03

### Fixed

- Faction IDs are not resolved for EveKillmails

## [0.7.4] - 2022-08-31

### Fixed

- Can not process killmails which have no zkb total value (#32)
- Can not created messages from killmails which have no zkb total value
- App requires Discord service to be installed for startup

## [0.7.3] - 2022-08-30

### Changed

- Retry task that need ESI when ESI is down or has too many errors

## [0.7.2] - 2022-07-31

### Changed

- Use retry-after value from header instead of content when being rate limited by Discord

## [0.7.1] - 2022-07-18

### Changed

- Added more NPC types, e.g. Angel Dreadnought

## [0.7.0] - 2022-07-16

>**Update Note**:<br>Please make sure to re-load eve types, or you might not see any of the newly added NPC types:<br>`python manage.py killtracker_load_eve`

### Added

- Ability to use NPC types and groups (e.g. Guristas Abolisher) when defining trackers

### Changed

- ZKB API errors are now logged as error, not warning

## [0.6.1] - 2022-06-16

### Changed

- Delivery to PyPI also as wheel

### Fixed

- Killtracker can no longer acquire a lock to fetch killmails from RedisQ when the lock key was not cleaned up on Redis

## [0.6.0] - 2022-06-05

### Added

- New clause: Exclude victim corporations (#29)
- New clause: Require attacker corporations/alliances to have final blow (#30)

### Changed

- Refactored lock logic to be agnostic of which django library is used for the redis cache, so it now works with both django-redis-cache and django-redis => compatible with AA 3

## [0.5.2] - 2022-05-15

### Fixed

- Trying to run a test killmail for a tracker on the admin site results in swagger file not found error

## [0.5.1] - 2022-03-02

### Changed

- AA3 compatibility update

## [0.5.0] - 2022-03-01

### Changed

- Add support for Django 3.2
- Remove support for Django 3.1
- Remove support for Python 3.6
- Improve Django 4 compatibility
- Update dependencies to reflect current incompatibility with AA 3

## [0.4.0] - 2021-05-26

### Added

- New clauses allows tracker to filter by characters belonging to users of an Auth state (e.g. Member) (Issue #26)

### Changed

- Add isort to CI

## [0.3.2] - 2021-03-03

### Changed

- Reduce load time for tracker list on admin site

## [0.3.1] - 2021-03-03

### Fixed

- Replaces celery_once with cache lock to ensure calls to ZKB RedisQ are atomic, because it looks like celery_once does not fully guarantee atomicity. [#10](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/10)

## [0.3.0] - 2021-02-20

### Update notes

Please re-run **killtracker_load_eve** to get all the newly added types.

### Added

- Add ping groups for trackers [#11](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/11)
- Option to set colors for Discord embed per tracker [#8](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/8)
- Author on Discord embed now shows victim organization [#8](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/8)
- Add Orbital Infrastructure to victim groups [#19](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/19)
- Option to deactivate webhook branding [#18](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/18)
- Added fighters and mining drones (e.g. Excavators) to tracker clauses [#12](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/12)
- Added timeouts to all tasks to prevent pileup during outage

### Changed

- Restructured tasks to improve scalability, performance and resilience [#20](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/20)
- Killtracker will no longer start when ESI is offline
- Remove support for Django 2.1 & 3.0 [#17](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/17)
- Significantly improved task performance with added caching
- Improved handling of potential HTTP 429 errors
- Improved handling of cases when ZKB does not return JSON
- Reduced default for KILLTRACKER_MAX_KILLMAILS_PER_RUN to 200
- Integrated allianceauth-app-utils

### Fixed

- Incompatible with django-redis-cache 3.0
- Fix attempt: Occasionally occurring transaction timeouts [#14](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/14)
- Migrations fail on MySQL 8 due to default for TextField
- Occasional 429 errors from ZKB RedisQ [#22](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/22)

## [0.2.6] - 2020-12-09

### Added

- Now sending proper user agent to ESI and ZKB
- pre-commit for white spaces, EOF and black

### Fixed

- Storing killmails is broken [#15](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/15)

## [0.2.5] - 2020-09-24

### Added

- Add test matrix for Django 3+
- Reformat for new Black version

## [0.2.4] - 2020-08-11

### Changed

- Initial data during installation is now loaded with a new management command: killtracker_load_eve

### Fixed

- Tracker will no longer break on ship types, which are added by CCP after the initial data load from ESI

## [0.2.3] - 2020-08-08

### Added

- Shows list of activated clauses for each tracker in tracker list
- Improved validations prevent the creation of invalid trackers

## [0.2.2] - 2020-08-04

### Changed

- Improved how "main group" is shown on killmails

### Fixed

- Retry of failed sending for killmails not working correctly
- Corp link of final attacker did not work ([#4](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/4))

## [0.2.1] - 2020-07-29

### Added

- Show region name on killmails ([#2](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/2))

### Changed

- Show ISK values in human readable form, we now use same format as zKillboard ([#3](https://gitlab.com/ErikKalkoken/aa-killtracker/-/issues/3))

## [0.2.0] - 2020-07-27

### Added

- Initial public release
