"""Database-shaped tools: SQLite query/insert helpers."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional

from ._base import P, Tool, _BaseToolRegistry


class DatabaseToolsMixin(_BaseToolRegistry):
    _SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def _register_database_tools(self) -> None:
        self.register_tool(Tool(
            name="sqlite_query",
            description="Execute SQL query on SQLite database",
            function=self._sqlite_query,
            category="database",
            parameters={
                "database_path": P("Path to SQLite database file", required=True),
                "query": P("SQL query to execute"),
                "params": P("Optional query parameters (list or dict)"),
            },
        ))
        self.register_tool(Tool(
            name="sqlite_insert",
            description="Insert data into SQLite database",
            function=self._sqlite_insert,
            category="database",
            side_effects=("write",),
            parameters={
                "database_path": P("Path to SQLite database file", required=True),
                "table": P("Table name", required=True),
                "data": P("Data to insert (dict or list of dicts)"),
            },
        ))

    def _sqlite_query(
        self,
        database_path: str,
        query: str,
        params: Optional[List] = None,
    ) -> Dict[str, Any]:
        try:
            normalized_query = query.strip()
            if normalized_query.endswith(";"):
                normalized_query = normalized_query[:-1].strip()
            if ";" in normalized_query:
                return {
                    "success": False,
                    "error": "sqlite_query allows a single SELECT statement only.",
                }
            if not normalized_query.upper().startswith("SELECT"):
                return {
                    "success": False,
                    "error": "sqlite_query only allows SELECT statements. Use sqlite_insert for writes.",
                }
            safe_db = self._sandbox_path(database_path)
            conn = sqlite3.connect(safe_db)
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            if cursor.description:
                results = cursor.fetchall()
                columns = (
                    [d[0] for d in cursor.description]
                    if cursor.description
                    else []
                )
                conn.close()
                return {
                    "success": True,
                    "result": results,
                    "results": results,
                    "columns": columns,
                    "meta": {
                        "database_path": safe_db,
                        "columns": columns,
                        "rows": len(results),
                    },
                }
            conn.close()
            return {
                "success": True,
                "result": [],
                "results": [],
                "columns": [],
                "message": "Query executed successfully",
                "meta": {
                    "database_path": safe_db,
                    "rows": cursor.rowcount,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _sqlite_insert(
        self,
        database_path: str,
        table: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            safe_db = self._sandbox_path(database_path)
            conn = sqlite3.connect(safe_db)
            cursor = conn.cursor()

            if isinstance(data, list):
                if not data:
                    return {"success": False, "error": "No data to insert"}
                columns = list(data[0].keys())
                if not self._valid_sql_identifiers(table, columns):
                    return {"success": False, "error": "Invalid table or column name"}
                placeholders = ", ".join(["?" for _ in columns])
                query = (
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({placeholders})"
                )
                values = [tuple(record[col] for col in columns) for record in data]
                cursor.executemany(query, values)
            else:
                columns = list(data.keys())
                if not self._valid_sql_identifiers(table, columns):
                    return {"success": False, "error": "Invalid table or column name"}
                values = list(data.values())
                placeholders = ", ".join(["?" for _ in columns])
                query = (
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({placeholders})"
                )
                cursor.execute(query, values)

            conn.commit()
            conn.close()
            return {
                "success": True,
                "result": f"Inserted data into {table}",
                "message": f"Inserted data into {table}",
                "meta": {
                    "database_path": safe_db,
                    "table": table,
                    "rows": len(data) if isinstance(data, list) else 1,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def _valid_sql_identifiers(cls, table: str, columns: List[str]) -> bool:
        names = [table, *columns]
        return all(cls._SQL_IDENTIFIER_RE.match(str(name or "")) for name in names)
