"""Recovery allowance belongs to a character and slot, not a transient PID."""

def used_for_session(saved,pid,character,instance):
    used=saved.get('used')
    if isinstance(used,bool) or not isinstance(used,int) or not 0<=used<=2:
        raise RuntimeError('恢复额度记录不完整，停止恢复')
    if saved.get('character'):
        if not character or saved['character']!=character or saved.get('instance','1')!=instance:
            raise RuntimeError('恢复额度所属角色或工具实例不符，停止恢复')
        return used
    if saved.get('game_pid')==pid:return used
    raise RuntimeError('旧恢复额度尚未绑定角色，需核对并迁移；不会按新PID清零')
