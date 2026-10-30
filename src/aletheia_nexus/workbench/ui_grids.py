"""Commit native AG Grid editors before reading actionable business data."""


async def read_edited_grid(grid):
    # Await the browser acknowledgement so a following data request cannot
    # overtake the active editor's commit. Failure must not submit old values.
    await grid.run_grid_method("stopEditing")
    return await grid.get_client_data()
