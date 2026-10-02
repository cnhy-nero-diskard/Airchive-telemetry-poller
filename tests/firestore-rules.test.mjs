import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { after, before, test } from "node:test";

import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from "@firebase/rules-unit-testing";
import {
  collection,
  deleteDoc,
  doc,
  getDoc,
  getDocs,
  limit,
  orderBy,
  query,
  setDoc,
  Timestamp,
  updateDoc,
  where,
} from "firebase/firestore";

const CLOSED_PROJECT_ID = "demo-airchive-closed";
const FIXTURE_PROJECT_ID = "demo-airchive-fixture";
const OWNER_UID = "fixture-owner-uid";
const OTHER_UID = "fixture-other-uid";
const DEVICE_ID = "fixture-airchive-device";
const OTHER_DEVICE_ID = "fixture-other-device";
const TELEMETRY = `devices/${DEVICE_ID}/telemetry`;
const DAILY_TOTALS = `devices/${DEVICE_ID}/dailyTotals`;
const HEALTH_PATH = `devices/${DEVICE_ID}/runtime/collector`;
const rulesSource = await readFile(new URL("../firestore.rules", import.meta.url), "utf8");

function emulatorEnrollmentRules(source) {
  let result = source;
  const replacements = [
    [
      /function mobileAccessEnabled\(\)\s*\{\s*return false;\s*\}/,
      "function mobileAccessEnabled() { return true; }",
    ],
    [
      "'__MOBILE_OWNER_UID_PENDING__'",
      `'${OWNER_UID}'`,
    ],
    [
      "'__AIRCHIVE_DEVICE_ID_PENDING__'",
      `'${DEVICE_ID}'`,
    ],
  ];

  for (const [search, replacement] of replacements) {
    const next = result.replace(search, replacement);
    assert.notEqual(next, result, `expected to find rules enrollment marker: ${search}`);
    result = next;
  }
  return result;
}

let closedEnv;
let fixtureEnv;

before(async () => {
  closedEnv = await initializeTestEnvironment({
    projectId: CLOSED_PROJECT_ID,
    firestore: { rules: rulesSource },
  });
  fixtureEnv = await initializeTestEnvironment({
    projectId: FIXTURE_PROJECT_ID,
    firestore: { rules: emulatorEnrollmentRules(rulesSource) },
  });
});

after(async () => {
  await Promise.all([closedEnv?.cleanup(), fixtureEnv?.cleanup()]);
});

test("checked-in rules stay closed until owner enrollment is explicitly enabled", async () => {
  const ownerDb = closedEnv.authenticatedContext(OWNER_UID).firestore();
  const anonymousDb = closedEnv.unauthenticatedContext().firestore();

  await assertFails(getDoc(doc(ownerDb, `devices/${DEVICE_ID}`)));
  await assertFails(getDoc(doc(anonymousDb, `devices/${DEVICE_ID}`)));
});

test("fixture rules allow only the enrolled owner to get the four approved paths", async () => {
  const ownerDb = fixtureEnv.authenticatedContext(OWNER_UID).firestore();

  await fixtureEnv.withSecurityRulesDisabled(async (context) => {
    const db = context.firestore();
    const observedAt = Timestamp.fromMillis(Date.UTC(2026, 8, 30, 12));
    await setDoc(doc(db, `devices/${DEVICE_ID}`), { deviceId: DEVICE_ID, alias: "AC" });
    await setDoc(doc(db, `${TELEMETRY}/sample-1`), {
      sampleId: "sample-1",
      observedAt,
      persistedAt: observedAt,
      reconciledAt: observedAt,
      energy: { intervalValue: null, unit: "Wh" },
      quality: { intervalStatus: "MISSING_ENERGY", flags: ["ENERGY_UNAVAILABLE"] },
      raw: { energy: { original: "provider-payload" }, state: {} },
    });
    await setDoc(doc(db, `${TELEMETRY}/sample-2`), {
      sampleId: "sample-2",
      observedAt: Timestamp.fromMillis(observedAt.toMillis() + 300_000),
      persistedAt: Timestamp.fromMillis(observedAt.toMillis() + 300_000),
      energy: { intervalValue: "0.12", unit: "kWh" },
      quality: { intervalStatus: "NORMAL", flags: [] },
      raw: { energy: {}, state: {} },
    });
    await setDoc(doc(db, `${DAILY_TOTALS}/2026-09-30`), {
      localDate: "2026-09-30",
      total: "1.25",
      totalNumber: 1.25,
      unit: "kWh",
      raw: { total: "1.25" },
    });
    await setDoc(doc(db, HEALTH_PATH), { lastSuccessAt: observedAt });
    await setDoc(doc(db, `devices/${DEVICE_ID}/metadata/current`), { version: "v1" });
    await setDoc(doc(db, `devices/${DEVICE_ID}/runtime/reconciliation`), { pending: {} });
    await setDoc(doc(db, `devices/${OTHER_DEVICE_ID}`), { deviceId: OTHER_DEVICE_ID });
    await setDoc(
      doc(db, `devices/${OTHER_DEVICE_ID}/telemetry/sample-1`),
      { sampleId: "sample-1" },
    );
  });

  const allowedPaths = [
    `devices/${DEVICE_ID}`,
    `${TELEMETRY}/sample-1`,
    `${DAILY_TOTALS}/2026-09-30`,
    HEALTH_PATH,
  ];
  for (const path of allowedPaths) {
    await assertSucceeds(getDoc(doc(ownerDb, path)));
  }

  const observation = await getDoc(doc(ownerDb, `${TELEMETRY}/sample-1`));
  assert.equal(observation.data().raw.energy.original, "provider-payload");
  assert.equal(observation.data().energy.intervalValue, null);
});

test("anonymous and other-owner reads are denied", async () => {
  const anonymousDb = fixtureEnv.unauthenticatedContext().firestore();
  const otherOwnerDb = fixtureEnv.authenticatedContext(OTHER_UID).firestore();
  const protectedPaths = [
    `devices/${DEVICE_ID}`,
    `${TELEMETRY}/sample-1`,
    `${DAILY_TOTALS}/2026-09-30`,
    HEALTH_PATH,
  ];

  for (const path of protectedPaths) {
    await assertFails(getDoc(doc(anonymousDb, path)));
    await assertFails(getDoc(doc(otherOwnerDb, path)));
  }
});

test("the owner cannot read another device or unlisted paths", async () => {
  const ownerDb = fixtureEnv.authenticatedContext(OWNER_UID).firestore();
  const deniedPaths = [
    `devices/${OTHER_DEVICE_ID}`,
    `devices/${OTHER_DEVICE_ID}/telemetry/sample-1`,
    `devices/${DEVICE_ID}/metadata/current`,
    `devices/${DEVICE_ID}/runtime/reconciliation`,
    `unlisted/root-document`,
  ];

  for (const path of deniedPaths) {
    await assertFails(getDoc(doc(ownerDb, path)));
  }
  await assertFails(getDocs(collection(ownerDb, "devices")));
  await assertFails(
    getDocs(query(collection(ownerDb, `devices/${OTHER_DEVICE_ID}/telemetry`), limit(250))),
  );
  await assertFails(
    getDocs(query(collection(ownerDb, `devices/${DEVICE_ID}/metadata`), limit(250))),
  );
});

test("telemetry and daily-total lists require a positive limit no greater than 250", async () => {
  const ownerDb = fixtureEnv.authenticatedContext(OWNER_UID).firestore();
  const telemetry = collection(ownerDb, TELEMETRY);
  const totals = collection(ownerDb, DAILY_TOTALS);

  await assertSucceeds(getDocs(query(telemetry, orderBy("observedAt"), limit(250))));
  await assertFails(getDocs(query(telemetry, orderBy("observedAt"))));
  await assertFails(getDocs(query(telemetry, orderBy("observedAt"), limit(251))));

  await assertSucceeds(getDocs(query(totals, orderBy("localDate"), limit(250))));
  await assertFails(getDocs(query(totals, orderBy("localDate"))));
  await assertFails(getDocs(query(totals, orderBy("localDate"), limit(251))));
});

test("bounded mutation-timestamp and daily-total queries work for the owner", async () => {
  const ownerDb = fixtureEnv.authenticatedContext(OWNER_UID).firestore();
  const watermark = Timestamp.fromMillis(Date.UTC(2026, 8, 1));

  const observedAtQuery = query(
    collection(ownerDb, TELEMETRY),
    where("observedAt", ">=", watermark),
    orderBy("observedAt"),
    limit(250),
  );
  const persistedAtQuery = query(
    collection(ownerDb, TELEMETRY),
    where("persistedAt", ">=", watermark),
    orderBy("persistedAt"),
    limit(250),
  );
  const reconciledAtQuery = query(
    collection(ownerDb, TELEMETRY),
    where("reconciledAt", ">=", watermark),
    orderBy("reconciledAt"),
    limit(250),
  );
  const dailyTotalsQuery = query(
    collection(ownerDb, DAILY_TOTALS),
    where("localDate", ">=", "2026-09-01"),
    orderBy("localDate"),
    limit(250),
  );

  assert.equal((await assertSucceeds(getDocs(observedAtQuery))).size, 2);
  assert.equal((await assertSucceeds(getDocs(persistedAtQuery))).size, 2);
  assert.equal((await assertSucceeds(getDocs(reconciledAtQuery))).size, 1);
  assert.equal((await assertSucceeds(getDocs(dailyTotalsQuery))).size, 1);
});

test("the enrolled owner cannot create, update, or delete any client document", async () => {
  const ownerDb = fixtureEnv.authenticatedContext(OWNER_UID).firestore();

  await assertFails(
    setDoc(doc(ownerDb, `${TELEMETRY}/client-created`), { sampleId: "client-created" }),
  );
  await assertFails(
    updateDoc(doc(ownerDb, `${TELEMETRY}/sample-1`), { "energy.intervalValue": "0" }),
  );
  await assertFails(deleteDoc(doc(ownerDb, `${TELEMETRY}/sample-1`)));
  await assertFails(setDoc(doc(ownerDb, `devices/${DEVICE_ID}/metadata/client-created`), {}));
  await assertFails(setDoc(doc(ownerDb, `${DAILY_TOTALS}/2026-10-01`), { total: "0" }));
  await assertFails(updateDoc(doc(ownerDb, `${DAILY_TOTALS}/2026-09-30`), { total: "0" }));
  await assertFails(deleteDoc(doc(ownerDb, `${DAILY_TOTALS}/2026-09-30`)));
  await assertFails(updateDoc(doc(ownerDb, `devices/${DEVICE_ID}`), { alias: "changed" }));
  await assertFails(deleteDoc(doc(ownerDb, `devices/${DEVICE_ID}`)));
  await assertFails(updateDoc(doc(ownerDb, HEALTH_PATH), { consecutiveFailures: 99 }));
  await assertFails(deleteDoc(doc(ownerDb, HEALTH_PATH)));
});
