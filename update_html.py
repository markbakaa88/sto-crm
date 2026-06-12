with open("/home/zxc/CRM/sto_crm/assets/index.html", "r", encoding="utf-8") as f:
    html = f.read()

# Make search bar look better
html = html.replace('<div class="search">', '<div class="search shadow-sm rounded-lg">')
html = html.replace('placeholder="Поиск по CRM"', 'placeholder="🔍 Быстрый поиск..."')

# Update title block 
html = html.replace('<div class="title-block">', '<div class="title-block" style="animation: fade-in 0.3s ease-out;">')

with open("/home/zxc/CRM/sto_crm/assets/index.html", "w", encoding="utf-8") as f:
    f.write(html)
