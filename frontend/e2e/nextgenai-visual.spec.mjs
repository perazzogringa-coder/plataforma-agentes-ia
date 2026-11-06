import { test, expect } from '@playwright/test';

// This suite is deliberately contract-level: every API response is synthetic.
// It validates routing, authenticated UI and responsive rendering without
// reading production data or asserting backend integration behaviour.
const contact = { id: 1, name: 'Contato Empresa Teste', phone: '5511999999999', unread_count: 1, archived: false };
const stages = [{ id: 10, name: 'Novos leads', position: 0, color: '#6750A4' }];

async function syntheticApi(page) {
  await page.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!['/auth/login', '/api', '/webhook', '/media-sources'].some(prefix => url.pathname.startsWith(prefix))) return route.continue();

    if (url.pathname === '/auth/login') {
      const master = (request.postData() || '').includes('master%40example.test');
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        token_type: 'bearer', company_id: master ? 100 : 200, client_id: master ? 1 : 2,
        user_id: master ? 10 : 20, user_type: master ? 'master' : 'user',
        sidebar_permissions: ['dashboard', 'chat', 'crm', 'company'], contact_permissions: {},
      }) });
    }
    let body = {};
    if (url.pathname.includes('/webhook/contacts')) body = { contacts: [contact], total: 1 };
    else if (url.pathname.includes('pipelines') || url.pathname.includes('stages')) body = stages;
    else if (url.pathname.includes('leads')) body = [];
    else if (url.pathname.includes('funnel') || url.pathname.includes('timeline')) body = [];
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
}

async function login(page, email) {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Senha').fill('synthetic-password');
  await page.getByRole('button', { name: /entrar/i }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

test('cliente: dashboard Mono, chat, contatos e board com contrato sintético', async ({ page }) => {
  await syntheticApi(page);
  await login(page, 'cliente@example.test');
  await expect(page.getByRole('heading', { name: 'Visão geral' })).toBeVisible();
  await page.getByRole('button', { name: /mostrar filtros/i }).click();
  await expect(page.getByLabel('Filtros do dashboard')).toBeVisible();
  await page.screenshot({ path: 'test-results/cliente-mono-desktop.png', fullPage: true });

  for (const path of ['/chat', '/contacts', '/crm']) {
    await page.goto(path);
    await expect(page.locator('body')).not.toContainText('Something went wrong');
    await page.screenshot({ path: `test-results/cliente-${path.slice(1)}-desktop.png`, fullPage: true });
  }
  await expect.poll(() => page.evaluate(() => localStorage.getItem('company_id'))).toBe('200');
});

test('master: sessão sintética mantém escopo próprio', async ({ page }) => {
  await syntheticApi(page);
  await login(page, 'master@example.test');
  await expect(page.getByRole('heading', { name: 'Visão geral' })).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem('company_id'))).toBe('100');
  await page.goto('/customers');
  await expect(page.locator('body')).not.toContainText('Something went wrong');
  await page.screenshot({ path: 'test-results/master-dashboard-desktop.png', fullPage: true });
});

test('mobile: Mono permanece navegável após remoção do Flowbite', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await syntheticApi(page);
  await login(page, 'cliente@example.test');
  await expect(page.getByRole('heading', { name: 'Visão geral' })).toBeVisible();
  await page.screenshot({ path: 'test-results/cliente-mono-mobile.png', fullPage: true });
});
