"""字段定义:媒介资料 + 交通信息(去程/返程),供 提取/校验/复核表/映射 共用。"""

MEDIA_FIELDS = ["媒体名称", "姓名", "职位", "电话", "身份证号", "收款方式", "收款账号", "开户行"]
LEG_FIELDS = ["方式", "日期", "出发城市", "到达城市", "航班车次", "出发时间", "到达时间", "航站楼"]
LEGS = ["去程", "返程"]


def flat_columns():
    """复核表/回填用的扁平列顺序。"""
    cols = list(MEDIA_FIELDS)
    for leg in LEGS:
        for f in LEG_FIELDS:
            cols.append(f"{leg}-{f}")
    return cols
