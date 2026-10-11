// Only rendered offer cards. Used by the scheduled browser collector.
({source, stop}) => {
  const clean = s => (s || '').replace(/[\u200b-\u200f\u2060]/g, '').replace(/\s+/g, ' ').trim();
  const number = s => Number((s || '').replace(/[^\d.,]/g, '').replace(',', '.'));
  const text = e => clean(e?.innerText);
  const result = new Map();
  const base = {ci: stop.ci, co: stop.co, adults: 2, currency: 'RUB', free: null, room: ''};
  function add(name, url, card, total, scale, extra = {}) {
    const t = text(card);
    const parsedUrl = new URL(url, location.href);
    const params = parsedUrl.searchParams;
    const dated = source === 'ozon' ? params.get('checkIn') === stop.ci && params.get('checkOut') === stop.co && params.get('Dlts') === '2'
      : source === 'yandex' ? params.get('checkinDate') === stop.ci && params.get('checkoutDate') === stop.co && params.get('adults') === '2'
      : source === 'sutochno' ? params.get('occupied') === `${stop.ci};${stop.co}` && params.get('guests_adults') === '2'
      : source === 'tvil' ? params.get('o[arrival]') === stop.ci && params.get('o[departure]') === stop.co && params.get('o[maleCount]') === '2'
      : source === 'tutu' ? params.get('check_in') === stop.ci && params.get('check_out') === stop.co && params.get('room[0]') === '2.'
      : source === 'onetwotrip' ? params.get('date_start') === stop.ci && params.get('date_end') === stop.co && params.get('rooms[0]') === '2' : false;
    if (!dated || !total || !name) return;
    const externalId = parsedUrl.pathname.replace(/\/$/, '').split('/').pop();
    const rating = t.match(/(?:^| )([1-9](?:[.,]\d)?|10(?:[.,]0)?) ([\d\s]+) отзыв/);
    const distance = t.match(/([\d.,]+)\s*(км|м)\s*(?:до центра|от центра|до\s+центра)/i) || t.match(/Центр ~ ([\d.,]+)\s*(км|м)/i);
    const km = distance ? number(distance[1]) / (distance[2] === 'м' ? 1000 : 1) : null;
    const cat = /хостел|капсул/i.test(name + ' ' + parsedUrl.pathname) || /•\s*Хостел/.test(t) ? 'Хостел' : /квартир|апартамент|студия|апарт-отель/i.test(name + ' ' + (extra.cat || '')) ? 'Квартира' : 'Отель';
    const {cat: categoryHint, ...details} = extra;
    const item = {...base, name: clean(name), url: parsedUrl.href, externalId, total,
      score: rating ? number(rating[1]) : null, scoreMax: scale, cnt: rating ? number(rating[2]) : 0,
      km, cat, star: number(name.match(/(\d)\s*\*/)?.[1]),
      free: /Бесплатная отмена/.test(t) ? true : null, ...details};
    result.set(item.externalId, item);
  }
  if (source === 'ozon') {
    for (const a of document.querySelectorAll('a[href*="/hotels/product/"]')) {
      const name = text(a);
      if (!name || /Выбрать|Авторизуйтесь|Смотреть/.test(name)) continue;
      let card = a.parentElement;
      for (let i = 0; card && i < 5; i++, card = card.parentElement) {
        const t = text(card);
        if (/\d+ ночей? •/.test(t) && /за ночь/.test(t)) {
          const total = t.match(/([\d\s]+)\s*₽\s+\d+\s+ноч/);
          const nights = t.match(/(\d+)\s+ноч/);
          if (Number(nights?.[1]) === stop.nights) add(name, a.href, card, number(total?.[1]), 5);
          break;
        }
      }
    }
  } else if (source === 'yandex') {
    for (const heading of document.querySelectorAll('h3[itemprop="name"]')) {
      const a = heading.querySelector('a[href]');
      if (!a) continue;
      let card = heading.parentElement;
      for (let i = 0; card && i < 8; i++, card = card.parentElement) {
        const price = card.querySelector('[data-qa="price"]');
        const t = text(card);
        if (price && /за ночь/.test(t) && Number(t.match(/(\d+)\s+ноч/)?.[1]) === stop.nights) {
          const room = t.match(/за ночь\s+(.+?)(?:До \d|Вам вернется|Выбрать|$)/)?.[1] || '';
          add(text(heading), a.href, card, number(text(price)), 5, {room});
          break;
        }
      }
    }
  } else if (source === 'sutochno') {
    for (const a of document.querySelectorAll('a.card-content')) {
      const card = a.closest('.card');
      if (!card) continue;
      const t = text(card);
      const total = t.match(/([\d\s]+)\s*₽\s+за\s+(\d+)\s+сут/);
      if (total && Number(total[2]) === stop.nights) {
        const addr = [...a.querySelectorAll('.card-content__property-text')].map(text).find(x => x.startsWith('Москва,'));
        add(text(a.querySelector('h2')), a.href, card, number(total[1]), 10,
          {addr: addr || '', room: text(a.querySelector('h2')), cat: text(a.querySelector('.card-content__object-subtext'))});
      }
    }
  } else if (source === 'onetwotrip') {
    for (const card of document.querySelectorAll('[data-hotel-id]')) {
      const t = text(card), name = text(card.querySelector('[title]'));
      if (Number(t.match(/За (\d+) ночей/)?.[1]) !== stop.nights) continue;
      const total = t.match(/([\d ]+)\s*₽/), score = t.match(/^([\d.,]+) /);
      add(name, location.href, card, number(total?.[1]), 10, {externalId: card.getAttribute('data-hotel-id'), score: score ? number(score[1]) : null, cat: /Апартамент/.test(t) ? 'Квартира' : ''});
    }
  } else if (source === 'tutu') {
    for (const a of document.querySelectorAll('a[href*="/h_"]')) {
      const name = text(a);
      if (!name) continue;
      let card = a;
      for (let i = 0; card && i < 7; i++, card = card.parentElement) {
        const t = text(card);
        if (Number(t.match(/(\d+)\s+ночей/)?.[1]) !== stop.nights || !/за ночь/.test(t)) continue;
        const money = [...card.querySelectorAll('*')].find(e => !e.children.length && /^\d[\d ]*\s*₽$/.test(text(e)));
        if (money) add(name, a.href, card, number(text(money)), 10);
        break;
      }
    }
  } else if (source === 'tvil') {
    for (const a of document.querySelectorAll('a[href*="from=search"]')) {
      const name = text(a);
      if (!name || /Фотограф|Смотреть/.test(name)) continue;
      let card = a.parentElement;
      for (let i = 0; card && i < 6; i++, card = card.parentElement) {
        const t = text(card);
        const total = t.match(/([\d\s]+)\s*₽\s*(?:за|\/)?\s*(\d+)\s+ноч/);
        if (total && Number(total[2]) === stop.nights) {
          const allPrice = card.querySelector('[data-testid="price-item-all"] [data-testid="price-value"]');
          const rating = t.match(/^(\d{2,3})\s+(?:Превосходно|Великолепно|Замечательно|Отлично|Хорошо|Очень хорошо)/);
          const count = t.match(/(\d+)\s+отзыв/);
          add(name, a.href, card, number(text(allPrice)) || number(total[1]), 100,
            {score: rating ? number(rating[1]) : null, cnt: count ? number(count[1]) : 0});
          break;
        }
      }
    }
  }
  return [...result.values()];
}
