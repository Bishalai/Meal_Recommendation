/**
 * Dashboard logic: recommendation, rating, history and profile.
 */
(() => {
  if (!MealMate.requireAuth()) return;

  const state = {
    time: 'lunch',          // currently selected meal time
    mainFood: null,         // name of the main dish, used when rating
    history: [],            // rows returned by /api/gethistory
  };

  const $ = (id) => document.getElementById(id);

  // -------------------------------------------------------------------------
  // Header / time picker
  // -------------------------------------------------------------------------
  $('dash-username').textContent = MealMate.session().username || 'there';

  const renderQuestion = () => {
    $('dash-question').textContent = `what\u2019s for ${state.time}?`;
  };

  document.querySelectorAll('#time-picker .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('#time-picker .chip').forEach((c) => c.classList.remove('is-active'));
      chip.classList.add('is-active');
      state.time = chip.dataset.time;
      renderQuestion();
    });
  });

  // -------------------------------------------------------------------------
  // Recommendation
  // -------------------------------------------------------------------------
  function toDishes(food) {
    const list = (value) => [].concat(value === undefined ? [] : value);
    const names = list(food.name);
    return names.map((name, i) => ({
      name,
      description: list(food.description)[i] || '',
      ingredients: list(food.ingredients)[i] || '',
      nutrition: list(food.nutrition)[i] || '0,0,0,0',
      diet: list(food.diet)[i] || '',
      type: list(food.type)[i] || '',
      time: list(food.time)[i] || '',
      amount: list(food.amount)[i] || '',
    }));
  }

  function nutritionOf(dish) {
    const [energy, carbs, fat, protein] = String(dish.nutrition).split(',').map(Number);
    return { energy, carbs, fat, protein };
  }

  function dishCard(dish, isMain) {
    const nut = nutritionOf(dish);
    const ingredients = String(dish.ingredients)
      .split(',')
      .filter(Boolean)
      .map((ing) => `<span class="tag">${ing.trim()}</span>`)
      .join('');

    return `
      <article class="dish ${isMain ? 'dish-main' : ''}">
        <header>
          <h3>${dish.name}</h3>
          <span class="badge">${dish.type}</span>
        </header>
        ${isMain ? '<p class="dish-label">Main dish</p>' : '<p class="dish-label">Goes well with it</p>'}
        <p class="dish-desc">${dish.description}</p>
        <div class="tag-row">${ingredients}</div>
        <ul class="nutrition">
          <li><strong>${round(nut.energy)}</strong><span>kcal</span></li>
          <li><strong>${round(nut.carbs)}</strong><span>g carbs</span></li>
          <li><strong>${round(nut.fat)}</strong><span>g fat</span></li>
          <li><strong>${round(nut.protein)}</strong><span>g protein</span></li>
        </ul>
        <p class="muted">${dish.amount ? `Serving: ${dish.amount} &middot; ` : ''}${dish.diet} &middot; ${dish.time}</p>
      </article>`;
  }

  const round = (value) => (Number.isFinite(value) ? Math.round(value * 10) / 10 : '-');

  function renderMacros(data) {
    $('macro-energy').textContent = `${data['recommended calories']} kcal`;
    $('macro-carbs').textContent =
      `${data['recommended carbohydrates(gm) min']} - ${data['recommended carbohydrates(gm) max']} g`;
    $('macro-fats').textContent =
      `${data['recommended fats(gm) min']} - ${data['recommended fats(gm) max']} g`;
    $('macro-protein').textContent =
      `${data['recommended protein(gm) min']} - ${data['recommended protein(gm) max']} g`;
  }

  async function recommend() {
    const errorBox = $('recommend-error');
    const loading = $('recommend-loading');
    const result = $('recommend-result');

    errorBox.hidden = true;
    result.hidden = true;
    loading.hidden = false;

    const data = await MealMate.api('/api/recommended', {
      method: 'POST',
      body: { time: state.time },
    });

    loading.hidden = true;

    if (data.error) {
      errorBox.textContent = data.error;
      errorBox.hidden = false;
      return;
    }

    const dishes = toDishes(data.food);
    state.mainFood = dishes[0].name;

    $('method-note').textContent = `How this was chosen: ${data['recommendation method'] || 'recommendation'}.`;
    $('dishes').innerHTML = dishes.map((dish, i) => dishCard(dish, i === 0)).join('');
    $('rating-feedback').hidden = true;
    setStars(0);
    renderMacros(data);
    result.hidden = false;
  }

  $('recommend-btn').addEventListener('click', recommend);

  // -------------------------------------------------------------------------
  // Rating
  // -------------------------------------------------------------------------
  const starButtons = Array.from(document.querySelectorAll('#rating-stars .star'));

  function setStars(value) {
    starButtons.forEach((star) => {
      star.classList.toggle('is-active', Number(star.dataset.rating) <= value);
    });
  }

  starButtons.forEach((star) => {
    star.addEventListener('click', async () => {
      if (!state.mainFood) return;
      const rating = Number(star.dataset.rating);
      setStars(rating);

      const data = await MealMate.api('/api/ratemeal', {
        method: 'POST',
        body: { food: state.mainFood, rating, time: state.time },
      });

      const feedback = $('rating-feedback');
      feedback.textContent = data.error
        ? data.error
        : `Thanks! You rated ${state.mainFood} ${rating}/5 - it is now in your history.`;
      feedback.hidden = false;
      loadHistory();
    });
  });

  // -------------------------------------------------------------------------
  // History
  // -------------------------------------------------------------------------
  async function loadHistory() {
    const data = await MealMate.api('/api/gethistory');
    const rows = (data.history || []).slice().reverse();
    const tbody = document.querySelector('#history-table tbody');
    const empty = $('history-empty');

    tbody.innerHTML = rows
      .map((row) => `
        <tr>
          <td>${row.date}</td>
          <td>${row.time}</td>
          <td>${row.food}</td>
          <td class="stars-cell">${'★'.repeat(Number(row.rating) || 0)}${'☆'.repeat(5 - (Number(row.rating) || 0))}</td>
        </tr>`)
      .join('');

    empty.hidden = rows.length > 0;
  }

  // -------------------------------------------------------------------------
  // Profile
  // -------------------------------------------------------------------------
  async function loadProfile() {
    const profile = await MealMate.api('/api/userdetails');
    if (profile.error) return;

    $('p-age').value = profile.age ?? '';
    $('p-sex').value = profile.sex || 'M';
    $('p-height').value = profile.height ?? '';
    $('p-weight').value = profile.weight ?? '';
    $('p-lifestyle').value = profile.lifestyle || 'lightlyactive';
    $('p-diet').value = profile.diet || 'vegetarian';
    $('p-tags').value = profile.tags || '';
    $('p-disease').value = profile.disease || '';
    $('p-allergy').value = profile.allergy || '';
  }

  $('profile-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const errorBox = $('profile-error');
    const successBox = $('profile-success');
    errorBox.hidden = true;
    successBox.hidden = true;

    const payload = Object.fromEntries(new FormData(event.target).entries());
    const data = await MealMate.api('/api/userdetails', { method: 'PUT', body: payload });

    if (data.error) {
      errorBox.textContent = data.error;
      errorBox.hidden = false;
      return;
    }

    successBox.textContent = 'Profile saved.';
    successBox.hidden = false;
    loadProfile();
  });

  $('delete-account').addEventListener('click', async () => {
    if (!window.confirm('Delete your account and all your data? This cannot be undone.')) return;

    const data = await MealMate.api('/api/userdetails', { method: 'DELETE' });
    if (data.error) {
      const errorBox = $('profile-error');
      errorBox.textContent = data.error;
      errorBox.hidden = false;
      return;
    }

    MealMate.clearSession();
    window.location.href = '/';
  });

  // -------------------------------------------------------------------------
  // First paint
  // -------------------------------------------------------------------------
  loadProfile();
  loadHistory();
  recommend();
})();
