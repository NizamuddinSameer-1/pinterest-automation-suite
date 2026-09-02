import sqlite3
c = sqlite3.connect('data/pre.db')
print('--- products with amzn.to / missing affiliate ---')
for r in c.execute("select id, substr(name,1,50), substr(affiliate_url,1,45) from products where affiliate_url like '%amzn.to%' or affiliate_url is null or affiliate_url=''"):
    print(r)
print('--- GENERATING stuck jobs ---')
for r in c.execute("select id, updated_at from jobs where current_state='GENERATING'"):
    print(r)
print('--- pins: destination_url empty ---')
print(c.execute("select count(*) from pin_drafts where destination_url is null or destination_url=''").fetchone()[0])
print('--- pins with board ---')
for r in c.execute("select board_name, count(*) from pin_drafts group by 1"):
    print(r)
