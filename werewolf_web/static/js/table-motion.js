// Public presentation only. No model calls, game timers or hidden-role reads.
(() => {
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const animations = new Map();
  let recovering = false;
  function arrive(element) {
    if (!element?.getClientRects().length || !element.animate) return;
    const old = animations.get(element);
    const style = old ? getComputedStyle(element) : null;
    const from = {opacity:style?.opacity || .55, transform:style?.transform || 'translateY(24px)'};
    old?.cancel();
    const frames = reduced?.matches ? [{opacity:.7}, {opacity:1}]
      : [from, {opacity:1, transform:'none'}];
    const animation = element.animate(frames, {duration:reduced?.matches ? 100 : 420, easing:'cubic-bezier(.19,1,.22,1)'});
    animations.set(element, animation);
    animation.finished.catch(() => {}).finally(() => {
      if (animations.get(element) === animation) animations.delete(element);
    });
  }
  const recover = applyRecoveryView;
  applyRecoveryView = view => {
    recovering = true;
    document.body.classList.add('replaying');
    try { return recover(view); }
    finally { recovering = false; document.body.classList.remove('replaying'); }
  };
  const update = updateRoundtable;
  updateRoundtable = event => {
    const phase = document.querySelector('#tablePhase').textContent;
    update(event);
    if (recovering) return;
    if (phase !== document.querySelector('#tablePhase').textContent) arrive(document.querySelector('.table-center'));
    // The callback precedes log/showAction; animate after their synchronous render.
    if (event.type === 'speech') queueMicrotask(() => {
      arrive(document.querySelector('.seat.speaking img'));
      arrive(document.querySelector('#speakerPortrait'));
      arrive(document.querySelector('.log')?.lastElementChild);
    });
    if (event.type === 'request') queueMicrotask(() => arrive(document.querySelector('#actionPanel')));
  };
  reduced?.addEventListener('change', () => {
    for (const animation of animations.values()) animation.cancel();
    animations.clear();
  });
})();
