/* Forgetting a memory and changing a Profilim selection are separate, explicit actions. */
import { NEEDS, readProfile, writeProfile } from './profile.js';

function profileSelection(record, profile) {
  if (record?.type === 'need' && Array.isArray(profile?.needs) && profile.needs.includes(record.key)) {
    return { field: 'needs', value: record.key,
      label: NEEDS.find((need) => need.key === record.key)?.label || record.label,
      active: profile.consent === true };
  }
  const place = typeof record?.key === 'string' ? /^(station|line):(.+)$/.exec(record.key) : null;
  if (record?.type !== 'place' || !place) return null;
  const field = place[1] === 'station' ? 'stations' : 'lines';
  return Array.isArray(profile?.[field]) && profile[field].includes(place[2])
    ? { field, value: place[2], label: place[2], active: true } : null;
}

function removeProfileSelection(record) {
  const profile = readProfile();
  const selected = profileSelection(record, profile);
  if (!selected) return false;
  return writeProfile({ ...profile,
    [selected.field]: profile[selected.field].filter((value) => value !== selected.value) });
}

function createForgetActions({ store, session, onChanged, refresh, status, button, list, addButton, tx }) {
  let forgottenRecord = null;
  function clear() { forgottenRecord = null; button.hidden = true; }

  async function forget(id, currentRow) {
    const items = [...list.querySelectorAll('.memory-item')];
    const index = items.indexOf(currentRow);
    const record = await store.forget(id);
    if (!record) throw new Error('Memory was not forgotten');
    await session.refreshActive?.(); await onChanged(); await refresh();
    const selected = profileSelection(record, readProfile());
    forgottenRecord = selected ? record : null;
    button.hidden = !selected;
    status.textContent = selected
      ? tx(selected.active ? 'forgot_profile_kept' : 'forgot_profile_inactive', { label: selected.label }) : tx('forgot');
    if (selected) button.focus();
    else {
      const after = [...list.querySelectorAll('.memory-item')];
      (after[Math.min(index, after.length - 1)]?.querySelector('button') || addButton).focus();
    }
  }

  async function removeFromProfile() {
    const record = forgottenRecord;
    const selected = profileSelection(record, readProfile());
    if (!record || !selected || !removeProfileSelection(record)) throw new Error('Profile was not changed');
    clear();
    await onChanged(); await refresh();
    const stillUsed = record.type === 'need' && store.requestNeeds({ profile: readProfile(),
      conversation: session.activeRecord?.() }).includes(record.key);
    status.textContent = stillUsed
      ? tx('removed_from_profile_still_used', { label: selected.label }) : tx('removed_from_profile');
    addButton.focus();
  }

  return { forget, removeFromProfile, clear };
}

export { createForgetActions, profileSelection, removeProfileSelection };
