"""Identity checks for the 156-byte item records already used by bag transfers."""

def item_identity(record):
    if len(record)!=156:raise RuntimeError('物品记录长度不符')
    length=record[0]
    if length>20:raise RuntimeError('物品名称结构不符')
    if not length:return {'name':'','uid':''}
    name=record[1:1+length].decode('gb18030')
    uid=record[0x90:0x98]
    if not any(uid):raise RuntimeError('物品唯一标识为空，停止出售')
    return {'name':name,'uid':uid.hex()}

def require_identity(actual,expected,phase):
    if actual!=expected:raise RuntimeError(phase+'物品唯一标识变化，停止；不会重复提交')

def validate_sale_removal(before,after,index):
    if len(before)!=40 or len(after)!=40:raise RuntimeError('背包容量不符')
    expected=before.copy();expected[index]={'name':'','uid':''}
    if after!=expected:raise RuntimeError('出售后背包物品标识未按预期变化，停止后续出售')
