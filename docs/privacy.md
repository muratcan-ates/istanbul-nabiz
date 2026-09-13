# Privacy in İstanbul Nabız — proactive alerts (epic E2)

> **Kısa özet (TR).** Uyarı aboneliğiniz — ev/iş konumunuz, izlediğiniz hatlar ve eşikleriniz —
> yalnızca **kendi tarayıcınızda** saklanır. Sunucu hiçbir kullanıcı kaydı tutmaz: ne konum, ne
> profil, ne geçmiş. Her kontrolde abonelik istekle birlikte gelir, sunucu yalnızca zaten herkes
> için çektiği İBB verisiyle kuralları değerlendirir ve yanıtı döndükten sonra her şeyi unutur.
> Hesap yok, çerez yok, sunucuda silinecek bir kaydınız yok. Her şeyi silmek için tarayıcınızdaki
> site verisini temizlemeniz yeterlidir (aşağıda §6).

This document describes how the alert engine in `src/nabiz/alerts/` handles user data. It is not a
promise bolted onto a finished feature; it is the shape of the feature. Where a claim here is
enforced by a test, the test is named.

---

## 1. The rule that shaped the design

`docs/NABIZ.md` §1.3:

> **No personal data is stored server-side.** Any feature involving a user's location, profile or
> history must be designed *privacy-first*: on-device state, explicit opt-in, data minimisation, no
> server logs of location. KVKK (Turkish data protection law) applies; treat it as a hard design
> constraint, not a footnote.

A conventional alert service inverts this: the server keeps subscriptions, runs them on a timer and
pushes. That design needs a row per user containing their home coordinates and what they watch — the
exact record this project refuses to hold. So the roles are swapped: **the client holds the
subscription and asks; the server is a stateless evaluator.**

## 2. Data flow

```
  BROWSER (the user's device)                        SERVER (stateless)                UPSTREAM
  ─────────────────────────────                      ──────────────────                ────────
  localStorage
    nabiz.alerts.subscription.v1   ──POST /api/alerts/check──►  parse_subscription()
      places[] {key,label,lat,lon}     (subscription in the       build_context()  ──►  İSPARK
      rules[]  {kind,thresholds}        request body, TLS)          reads only the      Metro
      muted_keys[] (in cooldown)                                    shared TTL cache    Traffic
                                                                    that every user     Air quality
    nabiz.alerts.cooldowns.v1                                       already shares      (one shared
      {dedupe_key: last_shown_ts}   ◄──200 {alerts:[…]}──────   evaluate_subscription()  PoliteClient,
                                        each alert carries          pure: no I/O,        never per user)
    client suppresses a key until       dedupe_key +               no writes, no logs
    cooldown_seconds have passed        cooldown_seconds           of user input
                                                              ── response sent ──►  every user-derived
                                                                 value is garbage-collected with the request
```

The only user-derived values the server ever touches are the coordinates in `places[]`, and only to
answer one question: *which air-quality station is nearest?* They live in local variables inside
`_air_quality_observations()` for the length of the call. They are not part of a cache key, not part
of the returned observation (which carries the **station**, not the place), and never logged.

## 3. What is stored where

| Data | Where it lives | Who can read it | Retention |
|---|---|---|---|
| Home/work coordinates, labels | Browser `localStorage` | The person using that browser | Until the user clears it |
| Watched lines, park ids, thresholds | Browser `localStorage` | Same | Until the user clears it |
| Which alerts were already shown (cooldown state) | Browser `localStorage` | Same | Until the user clears it |
| The subscription during one request | Server process memory | Nobody; discarded with the request | The request (milliseconds) |
| Alerts produced | Sent to that client only | That client | Not stored server-side at all |
| İBB data used to evaluate rules | Shared TTL cache (`src/ibb_mcp/cache.py`) | Everyone — it is public city data | One cache TTL (60 s – 1 day) |
| Measured line-headway table | `data/reference/line_reliability.json`, built from our own vehicle snapshots | Public | Rebuilt on demand |

There is no database, no user table, no session, no cookie and no account. **There is nothing to
breach, because there is nothing to store.**

## 4. What the server logs

One line, at `DEBUG`, per evaluation:

```
alerts evaluated: rules=[air_qualityx1, metro_disruptionx1, trafficx1] places=2 -> 2 alert
```

Rule kinds and counts. No coordinates, no place labels, no thresholds, no alert text, no identifier.
The summary is produced by `describe_subscription()`, which by construction can only emit counts.

Enforced by three tests in `tests/test_alerts.py`:

* `test_evaluation_never_writes_a_coordinate_to_a_log_record` — captures **every** record reaching
  the root logger during an evaluation that does produce alerts, and asserts the subscription's
  coordinates and label appear in none of them;
* `test_log_summary_of_a_subscription_carries_only_counts` — pins the exact summary string;
* `test_alert_sources_contain_no_logging_call_that_could_carry_a_location` — greps our own source for
  any `log.*(...)` call mentioning `lat`, `lon`, `coord`, `place` or `label`.

Validation errors are written the same way: `parse_subscription()` names the offending place **key**
("home"), never the coordinate, because an error string can reach a log
(`test_engine_rejects_coordinates_outside_istanbul_without_echoing_them`).

`test_evaluation_writes_nothing_to_disk` replaces `open()` and `Path.open()` with guards that fail on
any write mode, then evaluates a full subscription — proving the engine persists nothing even by
accident.

### The honest caveat: platform logs

The alert engine writes no location anywhere. The **hosting platform** is a different matter: an
Azure Container Apps ingress, like any reverse proxy, can log the client IP address and the request
path, and an IP address is personal data under KVKK and the GDPR. Two mitigations are part of the
deployment, not of this module:

1. the subscription travels in a **POST body**, never in a query string, so it cannot end up in an
   access-log URL (this is why the route is `POST`, not `GET`);
2. ingress access logging should be disabled or its retention set to the minimum before this feature
   is announced to real users; App Insights sampling must not be configured to capture request bodies.

Item 2 is a deployment gate, and is listed as such in the handoff rather than quietly assumed.

## 5. Why the cooldown is enforced by the client

Not sending the same alert every five minutes requires remembering "this user already saw key K at
time T". That is a per-user history — precisely the record this design refuses to keep. So the server
returns, with every alert, a stable `dedupe_key` and a suggested `cooldown_seconds`, and forgets both
the moment the response is written. The client stores `{dedupe_key: last_shown_at}` in
`localStorage` and suppresses a key until its cooldown has passed. It may also send the keys it is
currently sitting on as `muted_keys`, which the server uses to filter that one response and then
discards — request-scoped input, never state.

Three things fall out of this, all good:

* the suppression survives a server restart and a scale-out to several replicas, which a
  process-local table would not;
* the user can inspect and reset their own notification state — it is in their browser;
* dedupe keys are designed so that *new news gets through*: the key carries the metro notice's text
  digest, the air-quality **band**, and the parking severity, so an escalation (85% → full,
  moderate → unhealthy) produces a different key and is not swallowed by the previous cooldown
  (`test_parking_escalation_to_critical_changes_the_dedupe_key`,
  `test_air_quality_dedupe_key_tracks_the_band_not_the_exact_index`).

## 6. How a user deletes everything

There is no deletion request to send us, because we hold nothing. In the browser that runs the app:

1. use the app's **"Uyarıları sıfırla"** control (clears both `localStorage` keys), or
2. clear site data for the origin — Chrome/Edge: *Settings → Privacy → Site settings → View
   permissions and data stored across sites → select the site → Delete data*; Safari: *Settings →
   Privacy → Manage Website Data*; Firefox: *Settings → Privacy & Security → Cookies and Site Data →
   Manage Data*, or
3. in the browser console: `localStorage.removeItem("nabiz.alerts.subscription.v1");
   localStorage.removeItem("nabiz.alerts.cooldowns.v1")`.

After any of these, the next check sends no subscription and the server has nothing to evaluate. No
copy of the deleted data exists anywhere else — see §3.

## 7. Data minimisation, in practice

* **Coordinates are used, not kept.** They resolve a nearest station and are gone.
* **Labels are the user's own words** ("Ev", "İş"). They appear in the alert text sent back to that
  same user and nowhere else — not in a log, not in a cache key.
* **Bounds.** A subscription may declare at most 5 places, 20 rules and 10 car parks per rule
  (`MAX_PLACES`, `MAX_RULES`, `MAX_PARK_IDS`), which caps both the work one request can ask of
  İBB's shared gateway and the amount of location a single payload can carry.
* **Coordinates are validated against the İstanbul bounding box** and rejected otherwise: this service
  answers only for İstanbul, so accepting a coordinate anywhere else would be collecting data it has
  no use for.
* **Bus number plates remain excluded everywhere** (`DECISIONS.md` #7). The alert engine identifies a
  vehicle by door number or not at all.

## 8. What this design deliberately does not do (yet)

**True push notifications.** Web Push requires the server to store a push endpoint and its keys per
subscriber, and to run the evaluation on a timer — i.e. exactly the per-user record and the per-user
schedule this design avoids. Today the client polls while the page is open, which needs no stored
endpoint. Adding real push is therefore not a small feature but a **decision to record in
`DECISIONS.md`**, with the options being: (a) store only an opaque push endpoint plus an encrypted
subscription blob the server cannot read without the client's key, (b) keep polling and accept that
alerts only arrive while the app is open, or (c) delegate delivery to a channel the user already
controls (a Teams/e-mail digest they opt into). Until that decision is made, the honest claim is (b).

**Server-side alert history.** "Bana bu ay kaç uyarı geldi?" would need a per-user log. It is not
built, and would require the same kind of decision.

## 9. Licence and attribution

Alerts are derived from İBB Açık Veri Portalı data:
*Kamu sektörü bilgilerini içerir — İBB Açık Veri Portalı, İBB Açık Veri Lisansı (CC BY 4.0).*
Alerts are estimates, not official İBB announcements, and air-quality alerts are not health advice.
Both disclaimers ship inside the alert payload itself, not only in this document.
