---
status: approved
approved_at: 2026-09-19T07:03:22Z
last_modified: 2026-09-19T07:03:22Z
---

# Requirements Document

## Introduction

Eighty-three endpoints and no screens. This is the first of those screens: signing in, the
shell everything else will live inside, and the seven reports — the part of the system that
is worth looking at rather than operating.

**Why the reports first, and why this is not one big frontend feature.** Brief item 10 lists
seven screen areas. Building them as a single spec would mean one enormous review and weeks
before anything is usable. Reports are the right first slice because they are read-only —
no forms, no optimistic updates, no concurrency — while still exercising every layer the rest
will depend on: the session cookie, the generated client, tables, charts, the language and
direction switch, and money formatting. Once this lands, a screen is a known quantity.

<!-- assumed: the remaining screen areas — chart of accounts, partners, invoices and bills,
payments, the matching screen, bank reconciliation — follow as their own features, each
reusing this shell. -->

The frontend lives at `frontend/` in this repository (architecture §16), built with React,
TypeScript and Vite, using Ant Design for its dense tables and built-in right-to-left
support, and TanStack Query for server state (architecture §3).

**One constraint shapes everything here.** The API's session cookie is `HttpOnly` and
`SameSite=Lax`, so a browser will not send it on a cross-origin request. The application and
the API must therefore answer on the **same origin** — a development proxy, and one origin in
production. That is also what satisfies the API's origin check on writes, and it means no
CORS and no weakening of the cookie.

## Requirements

### R1 Signing in

**User Story:** As a finance user, I want to sign in and stay signed in, so that I can use the application without re-entering my password on every screen.

#### Acceptance Criteria

1. `R1.AC1` WHEN a person submits their email and password on the sign-in form, the system SHALL establish a session and open the application.
2. `R1.AC2` IF the email or password is wrong, THEN the system SHALL say that the credentials were not accepted, without revealing which part was wrong.
3. `R1.AC3` WHILE a sign-in request is in flight, the system SHALL disable the submit control so the same credentials cannot be sent twice.
4. `R1.AC4` WHEN a person who is already signed in opens the application, the system SHALL show the application rather than the sign-in form.
5. `R1.AC5` WHEN a person clicks sign out, the system SHALL end the session and show the sign-in form.
6. `R1.AC6` IF any request returns 401, THEN the system SHALL return the person to the sign-in form rather than showing an error.
7. `R1.AC7` The system SHALL keep the session only in the cookie the API sets.
8. `R1.AC8` The system SHALL keep no credential, session token or figure in browser storage.
9. `R1.AC9` WHEN a person opens a report's address without a session, the system SHALL show the sign-in form and then continue to that report.

### R2 The application shell

**User Story:** As a finance user, I want a consistent frame around every screen, so that I always know which company I am looking at and how to get elsewhere.

#### Acceptance Criteria

1. `R2.AC1` The system SHALL show the signed-in person's name or email, and the company being viewed, on every screen inside the application.
2. `R2.AC2` WHEN a person belongs to more than one company, the system SHALL let them switch company from the shell.
3. `R2.AC3` WHEN a person switches company, the system SHALL reload the current screen for the company they switched to.
4. `R2.AC4` The system SHALL navigate between reports without a full page reload.
5. `R2.AC5` The system SHALL put the current screen and its period in the browser's address, so a report can be bookmarked and shared.
6. `R2.AC6` WHEN a person uses the browser's back control, the system SHALL return to the previous screen and its period.
7. `R2.AC7` WHERE a person has no role in any company, the system SHALL say so plainly rather than showing an empty shell.

### R3 Arabic and right-to-left

**User Story:** As an Arabic-speaking accountant, I want the application in Arabic and laid out right to left, so that it reads naturally rather than being translated English.

#### Acceptance Criteria

1. `R3.AC1` The system SHALL offer English and Arabic.
2. `R3.AC2` WHEN a language is chosen, the system SHALL apply it to every label, heading and control.
3. `R3.AC3` WHEN Arabic is chosen, the system SHALL set the document direction to right-to-left so the whole layout mirrors.
4. `R3.AC4` WHEN Arabic is chosen, the system SHALL show each account's Arabic name where the chart provides one, falling back to the English name where it does not.
5. `R3.AC5` The system SHALL keep numbers, dates and currency amounts left-to-right within a right-to-left layout, because a reversed figure is a wrong figure.
6. `R3.AC6` WHEN a person changes language, the system SHALL keep them on the same screen with the same period.
7. `R3.AC7` The system SHALL remember the chosen language for the next visit.
8. `R3.AC8` The system SHALL contain no user-facing text that exists in only one of the two languages.

### R4 Money and dates on screen

**User Story:** As an accountant, I want figures shown exactly as the ledger holds them, so that what I read is what I could file.

#### Acceptance Criteria

1. `R4.AC1` The system SHALL format money to the currency's decimal places with thousands separators.
2. `R4.AC2` The system SHALL NOT recompute, round or re-total any figure the API returned.
3. `R4.AC3` The system SHALL show the currency of the figures on every report.
4. `R4.AC4` The system SHALL show negative amounts unmistakably, and the same way on every report.
5. `R4.AC5` The system SHALL align figures on their decimal point in every column of figures.
6. `R4.AC6` The system SHALL show dates in a form whose day and month cannot be confused.
7. `R4.AC7` WHERE a figure is zero, the system SHALL show a dash rather than 0.00, so the eye finds the figures that matter.

### R5 Reading a report

**User Story:** As an owner, I want each report on its own screen, so that I can read the business's position without asking anyone.

#### Acceptance Criteria

1. `R5.AC1` The system SHALL present the trial balance, profit and loss, balance sheet, cash flow, aged receivables, aged payables and VAT return, each on its own screen.
2. `R5.AC2` The system SHALL show each report's company, period, currency and the moment its figures were read.
3. `R5.AC3` WHEN a report's rows are nested, the system SHALL show the hierarchy with its subtotals.
4. `R5.AC4` WHEN a person collapses a group, the system SHALL hide its children and keep its subtotal.
5. `R5.AC5` WHEN the profit and loss is shown, the system SHALL make gross profit and the net result visually distinct from the accounts they summarise.
6. `R5.AC6` WHEN the balance sheet is shown, the system SHALL state whether it balances.
7. `R5.AC7` WHEN the VAT return is shown, the system SHALL label each box with its ZATCA number and name.
8. `R5.AC8` WHILE a report is loading, the system SHALL show that it is loading rather than an empty screen or a flash of nothing.
9. `R5.AC9` WHERE a report has no figures for the chosen period, the system SHALL say so rather than showing an empty table.

### R6 Choosing the period

**User Story:** As an accountant, I want to change the period without editing a URL, so that comparing months or quarters is quick.

#### Acceptance Criteria

1. `R6.AC1` WHEN a person picks a named period such as a quarter or the fiscal year to date, the system SHALL reload the report for that period.
2. `R6.AC2` WHEN a person picks explicit start and end dates, the system SHALL reload the report for that range.
3. `R6.AC3` IF a person picks an end date before the start date, THEN the system SHALL say so and leave the report as it was.
4. `R6.AC4` WHEN a person moves from one report to another, the system SHALL keep the period they had chosen.
5. `R6.AC5` WHERE a report is as of a single date rather than a range, the system SHALL ask for one date.
6. `R6.AC6` WHEN the profit and loss is shown, the system SHALL let a person add the preceding period alongside.

### R7 Charts

**User Story:** As an owner, I want to see the shape of the business, so that I notice a trend before it becomes a problem.

#### Acceptance Criteria

1. `R7.AC1` WHEN the profit and loss is shown, the system SHALL chart income and expenses over the months of the period.
2. `R7.AC2` WHEN aged receivables are shown, the system SHALL chart the total in each ageing bucket.
3. `R7.AC3` The system SHALL label every chart axis with its unit, naming the currency.
4. `R7.AC4` The system SHALL draw every chart from the same figures as the table beside it, with no separate rounding or aggregation.
5. `R7.AC5` The system SHALL keep charts readable in both languages and in right-to-left layout.
6. `R7.AC6` WHERE a period has too few points to show a trend, the system SHALL show the figures without a chart rather than a misleading line.

### R8 Drilling into a figure

**User Story:** As anyone reading a report, I want to click a figure and see the entries behind it, so that I can check it rather than trust it.

#### Acceptance Criteria

1. `R8.AC1` WHEN a person clicks an account's figure on any report, the system SHALL show that account's entries for the same period.
2. `R8.AC2` WHEN account entries are shown, the system SHALL show each line's date, entry number, partner, description and running balance.
3. `R8.AC3` WHEN an entry line came from an invoice, bill or payment, the system SHALL show that document's number.
4. `R8.AC4` WHEN a person leaves the detail, the system SHALL return them to the report and the position they were reading.
5. `R8.AC5` The system SHALL show the account's closing balance on the detail, so it can be compared with the figure that was clicked.

### R9 When something goes wrong

**User Story:** As a finance user, I want to be told what happened, so that I can act rather than guess or lose work.

#### Acceptance Criteria

1. `R9.AC1` IF a request is refused for want of permission, THEN the system SHALL say which action was not permitted rather than showing a blank screen.
2. `R9.AC2` IF a request is rejected as invalid, THEN the system SHALL show the message the API returned against the input that caused it.
3. `R9.AC3` IF a request fails for a reason the system does not recognise, THEN the system SHALL say that something went wrong and offer to try again.
4. `R9.AC4` IF the network is unreachable, THEN the system SHALL say so in words distinct from a refusal by the server.
5. `R9.AC5` WHILE a request is retrying, the system SHALL leave the last figures on screen rather than clearing them.
6. `R9.AC6` The system SHALL NOT show a stack trace, an internal identifier or an error code without words a person can act on.

### R10 Talking to the API

**User Story:** As a developer, I want the client generated from the API's own description, so that a change to a response is a compile error rather than a bug in production.

#### Acceptance Criteria

1. `R10.AC1` The system SHALL generate its TypeScript API client from the API's OpenAPI description.
2. `R10.AC2` WHEN the generated client is out of date with the API, the build SHALL fail rather than silently disagree.
3. `R10.AC3` The system SHALL send every request to the same origin it was served from, so the session cookie is sent and no CORS is needed.
4. `R10.AC4` The system SHALL cache report responses per company and period.
5. `R10.AC5` WHEN the company changes, the system SHALL discard the cached responses of the company left behind.
6. `R10.AC6` The system SHALL use no floating-point arithmetic on any amount it receives.

### R11 Keyboard and assistive technology

**User Story:** As an accountant who works by keyboard, I want to reach everything without a mouse, so that entering and reading a day's figures is not slower than it needs to be.

#### Acceptance Criteria

1. `R11.AC1` The system SHALL make every control reachable and operable by keyboard alone.
2. `R11.AC2` The system SHALL show which element has keyboard focus at all times.
3. `R11.AC3` WHEN a report finishes loading, the system SHALL announce it to assistive technology.
4. `R11.AC4` The system SHALL give every chart a text alternative stating what it shows.
5. `R11.AC5` The system SHALL associate every form input with its label.

## Non-Functional Requirements

- `NFR1` The system SHALL show a signed-in person their first report within two seconds on a broadband connection.
- `NFR2` The system SHALL ship an initial JavaScript bundle no larger than 400 KB compressed, excluding lazily loaded report screens.
- `NFR3` The system SHALL meet WCAG 2.1 AA for colour contrast and keyboard operation on every screen in this feature.
- `NFR4` The system SHALL be typed with TypeScript in strict mode, with no `any` in application code.
- `NFR5` The system SHALL render correctly from 360 pixels wide upward, because a controller checks figures on a phone.
- `NFR6` The system SHALL hold no financial figure in browser storage, so signing out on a shared machine leaves nothing behind.

## Constraints And Dependencies

- `C1` React, TypeScript, Vite, Ant Design, TanStack Query and react-i18next, per architecture §3.
- `C2` The frontend lives at `frontend/` in this repository, per architecture §16.
- `C3` The API's session cookie is `HttpOnly` and `SameSite=Lax`, so the application and the API must answer on one origin: a proxy in development, one origin in production.
- `C4` Writes must carry an accepted `Origin`, which same-origin serving satisfies; this feature reads only, but the constraint governs its setup.
- `C5` The reports API delivered by `financial-reports` is the only source of figures.
- `C6` Test runs on the development machine are memory-capped: `vitest --maxWorkers=2`.
- `C7` Every feature goes through the Walden gates, and CI must pass before merge.

## Out Of Scope

- Chart of accounts, partners, invoices and bills, payments, the matching screen and bank reconciliation — each its own feature on this shell.
- Creating, editing or posting anything: this feature reads.
- CSV, Excel and PDF export (decision D13, its own feature).
- Dashboards and KPI tiles (Phase 2).
- Inviting users and managing roles from the browser.
- Offline use and any service worker.
- Dark mode.
- Hijri date display (an option the brief defers).
