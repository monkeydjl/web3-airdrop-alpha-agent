"""Import utilities for projects data.

支持导入格式:
- Excel (.xlsx)
- CSV (.csv)
"""

import csv
import io
from typing import List, Dict, Any, Optional

import pandas as pd
import structlog

from app.agents.base import RawProject

logger = structlog.get_logger(__name__)


def import_projects_from_excel(file_content: bytes) -> List[Dict[str, Any]]:
    """从 Excel 文件导入项目.

    Args:
        file_content: Excel 文件的字节数据

    Returns:
        项目列表

    Raises:
        ValueError: 文件格式错误或必填字段缺失
    """
    try:
        # 读取 Excel
        df = pd.read_excel(io.BytesIO(file_content))

        # 验证必填列
        required_columns = ["项目名称", "name"]
        has_required = any(col in df.columns for col in required_columns)

        if not has_required:
            raise ValueError("Excel 文件必须包含 '项目名称' 或 'name' 列")

        # 标准化列名（支持中英文）
        column_mapping = {
            "项目名称": "name",
            "name": "name",
            "URL": "url",
            "url": "url",
            "赛道": "sector",
            "sector": "sector",
            "阶段": "stage",
            "stage": "stage",
            "有测试网": "has_testnet",
            "has_testnet": "has_testnet",
            "有积分计划": "has_points_program",
            "has_points_program": "has_points_program",
            "未发币": "no_token_yet",
            "no_token_yet": "no_token_yet",
            "近期融资": "recent_funding",
            "recent_funding": "recent_funding",
        }

        # 重命名列
        df = df.rename(columns=column_mapping)

        # 转换为项目列表
        projects = []
        for _, row in df.iterrows():
            # 跳过空行
            if pd.isna(row.get("name")):
                continue

            project = {
                "name": str(row.get("name", "")).strip(),
                "url": str(row.get("url", "")) if not pd.isna(row.get("url")) else None,
                "sector": str(row.get("sector", "")) if not pd.isna(row.get("sector")) else None,
                "stage": str(row.get("stage", "")) if not pd.isna(row.get("stage")) else None,
            }

            # 布尔字段处理
            bool_fields = ["has_testnet", "has_points_program", "no_token_yet", "recent_funding"]
            for field in bool_fields:
                value = row.get(field)
                if pd.isna(value):
                    project[field] = False
                elif isinstance(value, bool):
                    project[field] = value
                elif isinstance(value, str):
                    project[field] = value.lower() in ["true", "是", "yes", "1", "√"]
                else:
                    project[field] = bool(value)

            projects.append(project)

        logger.info(
            "import.excel.success",
            project_count=len(projects),
        )

        return projects

    except Exception as e:
        logger.error(
            "import.excel.failed",
            error=str(e),
            exc_info=True,
        )
        raise ValueError(f"Excel 导入失败: {str(e)}")


def import_projects_from_csv(file_content: str) -> List[Dict[str, Any]]:
    """从 CSV 文件导入项目.

    Args:
        file_content: CSV 文件的字符串数据

    Returns:
        项目列表

    Raises:
        ValueError: 文件格式错误或必填字段缺失
    """
    try:
        # 读取 CSV
        df = pd.read_csv(io.StringIO(file_content))

        # 验证必填列
        required_columns = ["项目名称", "name"]
        has_required = any(col in df.columns for col in required_columns)

        if not has_required:
            raise ValueError("CSV 文件必须包含 '项目名称' 或 'name' 列")

        # 标准化列名（与 Excel 相同）
        column_mapping = {
            "项目名称": "name",
            "name": "name",
            "URL": "url",
            "url": "url",
            "赛道": "sector",
            "sector": "sector",
            "阶段": "stage",
            "stage": "stage",
            "有测试网": "has_testnet",
            "has_testnet": "has_testnet",
            "有积分计划": "has_points_program",
            "has_points_program": "has_points_program",
            "未发币": "no_token_yet",
            "no_token_yet": "no_token_yet",
            "近期融资": "recent_funding",
            "recent_funding": "recent_funding",
        }

        df = df.rename(columns=column_mapping)

        # 转换为项目列表（与 Excel 相同逻辑）
        projects = []
        for _, row in df.iterrows():
            if pd.isna(row.get("name")):
                continue

            project = {
                "name": str(row.get("name", "")).strip(),
                "url": str(row.get("url", "")) if not pd.isna(row.get("url")) else None,
                "sector": str(row.get("sector", "")) if not pd.isna(row.get("sector")) else None,
                "stage": str(row.get("stage", "")) if not pd.isna(row.get("stage")) else None,
            }

            bool_fields = ["has_testnet", "has_points_program", "no_token_yet", "recent_funding"]
            for field in bool_fields:
                value = row.get(field)
                if pd.isna(value):
                    project[field] = False
                elif isinstance(value, bool):
                    project[field] = value
                elif isinstance(value, str):
                    project[field] = value.lower() in ["true", "是", "yes", "1", "√"]
                else:
                    project[field] = bool(value)

            projects.append(project)

        logger.info(
            "import.csv.success",
            project_count=len(projects),
        )

        return projects

    except Exception as e:
        logger.error(
            "import.csv.failed",
            error=str(e),
            exc_info=True,
        )
        raise ValueError(f"CSV 导入失败: {str(e)}")


def validate_imported_projects(projects: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[str]]:
    """验证导入的项目数据.

    Args:
        projects: 导入的项目列表

    Returns:
        (有效项目列表, 错误信息列表)
    """
    valid_projects = []
    errors = []

    for i, project in enumerate(projects):
        row_num = i + 2  # Excel/CSV 行号（从2开始，因为有表头）

        # 检查必填字段
        if not project.get("name"):
            errors.append(f"第 {row_num} 行: 项目名称不能为空")
            continue

        # 检查项目名称长度
        if len(project["name"]) > 100:
            errors.append(f"第 {row_num} 行: 项目名称过长（最多100字符）")
            continue

        # 检查 URL 格式（如果提供）
        if project.get("url") and not project["url"].startswith(("http://", "https://")):
            errors.append(f"第 {row_num} 行: URL 格式无效")
            continue

        valid_projects.append(project)

    logger.info(
        "import.validation.complete",
        total=len(projects),
        valid=len(valid_projects),
        errors=len(errors),
    )

    return valid_projects, errors


def create_import_template_excel() -> bytes:
    """创建 Excel 导入模板.

    Returns:
        Excel 模板的字节数据
    """
    # 模板数据（示例）
    template_data = {
        "项目名称": ["LayerX", "DefiHub", "GameChain"],
        "URL": ["https://layerx.xyz", "https://defihub.io", "https://gamechain.com"],
        "赛道": ["L2", "DeFi", "Gaming"],
        "阶段": ["testnet", "mainnet", "testnet"],
        "有测试网": [True, False, True],
        "有积分计划": [True, True, False],
        "未发币": [True, False, True],
        "近期融资": [True, False, True],
    }

    df = pd.DataFrame(template_data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='导入模板', index=False)

        # 美化
        workbook = writer.book
        worksheet = writer.sheets['导入模板']

        # 标题行样式
        from openpyxl.styles import Font, PatternFill, Alignment

        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)

        for cell in worksheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # 调整列宽
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 40)
            worksheet.column_dimensions[column_letter].width = adjusted_width

    output.seek(0)
    return output.read()
