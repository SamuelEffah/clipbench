// Station-specific shortcut dialogs share native focus trapping and Escape dismissal.
const keyPairs = [[$("helpBtn"), $("keysPop")], [$("helpBtn3"), $("keysPop")], [$("helpBtn2"), $("keysShort")]];

function setKeys(pop, open) {
  for (const dialog of new Set(keyPairs.map(([, x]) => x))) {
    if (dialog.open && (!open || dialog !== pop)) dialog.close();
  }
  if (open && pop && !pop.open) pop.showModal();
  keyPairs.forEach(([button, dialog]) => button.setAttribute("aria-expanded", String(dialog.open)));
}
keyPairs.forEach(([button, dialog]) => {
  button.setAttribute("aria-haspopup", "dialog");
  button.setAttribute("aria-controls", dialog.id);
  button.onclick = () => setKeys(dialog, !dialog.open);
});
for (const dialog of new Set(keyPairs.map(([, x]) => x))) {
  dialog.querySelector('.keys-close').onclick = () => setKeys(null, false);
  dialog.addEventListener('close', () => {
    keyPairs.forEach(([button, target]) => button.setAttribute('aria-expanded', String(target.open)));
  });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) setKeys(null, false);
  });
}
