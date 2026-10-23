"""Exact names supplied by the user; category determines the required merchant."""
HEAD = '''青铜头盔 魔法头盔 道士头盔 骷髅头盔 黑铁头盔'''.split()
NECK = '''金项链 传统项链 白金项链 黄色水晶项链 黑檀项链 黑色水晶项链 白色虎齿项链 琥珀项链 魔鬼项链 凤凰明珠 灯笼项链 蓝翡翠项链 竹笛 放大镜'''.split()
WRIST = '''铁手镯 小手镯 银手镯 大手镯 钢手镯 皮制手套 夏普儿手镯 坚固手套 魔法手镯 辟邪手镯 黑檀手镯 道士手镯 死神手套 金手镯 魔力手镯'''.split()
RING = '''古铜戒指 六角戒指 玻璃戒指 牛角戒指 生铁戒指 蓝色水晶戒指 黑色水晶戒指 蛇眼戒指 珍珠戒指 金戒指 骷髅戒指 魅力戒指 道德戒指 降妖除魔戒指 珊瑚戒指'''.split()
ARMOR = '''重盔甲(男) 重盔甲(女) 魔法长袍(男) 魔法长袍(女) 灵魂战衣(男) 灵魂战衣(女) 轻型盔甲(男) 轻型盔甲(女) 战神盔甲(男) 战神盔甲(女) 恶魔长袍(男) 恶魔长袍(女) 幽灵战衣(男) 幽灵战衣(女)'''.split()
WEAPONS = frozenset('木剑 铁剑 短剑 青铜斧 罗刹 八荒 海魂 半月 凌风 偃月 破魂 降魔 斩马刀 修罗 凝霜'.split())
CATEGORIES = {name: category for category, names in (
    ('头盔', HEAD), ('项链', NECK), ('手镯', WRIST), ('戒指', RING),
    ('衣服', ARMOR), ('武器', WEAPONS)) for name in names}


def sale_plan(inventory):
    return [{'slot': i + 1, 'name': name, 'category': CATEGORIES[name],
             'current_shop_supported': name in WEAPONS}
            for i, name in enumerate(inventory) if name in CATEGORIES]


def project_tile(player_xy, player_draw, target_xy):
    return (player_draw[0] + 48 * (target_xy[0] - player_xy[0]),
            player_draw[1] + 32 * (target_xy[1] - player_xy[1]))
