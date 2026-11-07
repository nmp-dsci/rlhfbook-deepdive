// Shared behaviour for review pages. Every page loads this; `make check` enforces it.

// Inside Lavish, a click on a plain link opens an annotation card and does not follow the link.
// data-lavish-action makes links work, so a citation can always be followed. External links need a
// new tab because the review page runs in a sandboxed frame. Text around a link stays annotatable.
for (const link of document.querySelectorAll('a[href]')) {
  link.setAttribute('data-lavish-action', '');
  if (/^https?:/.test(link.getAttribute('href'))) {
    link.target = '_blank';
    link.rel = 'noopener';
  }
}

// Jumping to a source keeps your place: the source gets a button that returns to the chip.
let back = null;
document.addEventListener('click', (event) => {
  const chip = event.target.closest?.('a.chip[href^="#s"]');
  const source = chip && document.querySelector(chip.getAttribute('href'));
  if (!source) return;
  back?.remove();
  back = document.createElement('button');
  back.type = 'button';
  back.className = 'btn btn-sm';
  back.textContent = 'Back to the text';
  back.onclick = () => {
    chip.scrollIntoView({ block: 'center' });
    back.remove();
  };
  source.querySelector('figcaption')?.append(' ', back);
});

// Buttons that queue a prompt only work in a Lavish session.
addEventListener('load', () => {
  if (window.lavish) return;
  for (const button of document.querySelectorAll('.launch')) button.remove();
});
