(function () {
  var toggle = document.querySelector('.nav-toggle');
  var menu = document.getElementById('menu');
  if (toggle && menu) {
    toggle.addEventListener('click', function () {
      var open = menu.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  // Confirmação antes de ações importantes
  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!window.confirm(form.getAttribute('data-confirm'))) e.preventDefault();
    });
  });
  // Evita envio duplicado por cliques repetidos (o servidor também valida)
  document.querySelectorAll('form[method="post"]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (e.defaultPrevented) return;
      var btn = form.querySelector('button[type="submit"]');
      if (btn) setTimeout(function () { btn.disabled = true; btn.classList.add('loading'); }, 0);
    });
  });
  // Selects/datas que recarregam a página para atualizar as opções
  document.querySelectorAll('[data-autosubmit]').forEach(function (el) {
    el.addEventListener('change', function () { el.form.submit(); });
  });
})();
