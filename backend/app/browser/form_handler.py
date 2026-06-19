import logging
import tempfile
import os
from typing import Dict, Any, List, Optional
from playwright.async_api import Page, ElementHandle
from app.config import settings

logger = logging.getLogger("autoapply_ai.browser.form_handler")

class FormHandler:
    @staticmethod
    async def detect_multi_step(page: Page) -> bool:
        """Helper to detect if the form page is a multi-step form."""
        step_indicators = [
            "step 1", "step 2", "next step", "previous step",
            "progress", "page 1 of", "page 2 of"
        ]
        try:
            buttons = await page.query_selector_all("button, input[type='button'], input[type='submit']")
            has_next_button = False
            for btn in buttons:
                if await btn.is_visible():
                    text = (await btn.inner_text()).lower()
                    if any(x in text for x in ["next", "continue", "proceed"]):
                        has_next_button = True
                        break
        except Exception:
            has_next_button = False

        try:
            content = (await page.content()).lower()
            has_step_text = any(indicator in content for indicator in step_indicators)
        except Exception:
            has_step_text = False

        return has_next_button or has_step_text

    @staticmethod
    async def extract_form_fields(page: Page) -> List[Dict[str, Any]]:
        """Extract metadata for all input, textarea, and select elements on the active page."""
        fields = []
        
        # Detect iframe context
        target = page
        for frame in page.frames:
            if "greenhouse.io/embed" in frame.url or "greenhouse.io/job_app" in frame.url or "greenhouse.io/job_board" in frame.url:
                target = frame
                break
                
        try:
            is_multi_step = await FormHandler.detect_multi_step(page)
        except Exception:
            is_multi_step = False
            
        elements = await target.query_selector_all("input, textarea, select")
        radio_groups = {}
        
        for idx, el in enumerate(elements):
            try:
                # Filter visible fields
                if not await el.is_visible():
                    continue
                    
                tag_name = await el.evaluate("el => el.tagName.toLowerCase()")
                el_type = await el.get_attribute("type") or "text"
                el_id = await el.get_attribute("id") or ""
                el_name = await el.get_attribute("name") or ""
                placeholder = await el.get_attribute("placeholder") or ""
                aria_label = await el.get_attribute("aria-label") or ""
                
                # Required check
                required = False
                req_attr = await el.get_attribute("required")
                aria_req = await el.get_attribute("aria-required")
                if req_attr is not None or aria_req == "true":
                    required = True
                
                # Check for options if it's a select dropdown
                options = []
                if tag_name == "select":
                    try:
                        options = await el.evaluate("""el => {
                            return Array.from(el.options).map(opt => ({
                                value: opt.value,
                                text: opt.text.trim()
                            }));
                        }""")
                    except Exception as opt_err:
                        logger.warning(f"Error extracting select options: {opt_err}")
                
                # Try to find associated label text
                label_text = ""
                if el_id:
                    label_el = await target.query_selector(f"label[for='{el_id}']")
                    if label_el:
                        label_text = await label_el.inner_text()
                        
                if not label_text:
                    # Look for nearby text inside parent nodes
                    label_text = await el.evaluate(
                        "el => { "
                        "  let parent = el.parentElement; "
                        "  if (parent) { return parent.innerText.split('\\n')[0]; } "
                        "  return ''; "
                        "}"
                    )
                
                label_text = label_text.strip()
                if label_text and "*" in label_text:
                    required = True
                
                # Radio group handling
                if el_type == "radio" and el_name:
                    opt_val = await el.get_attribute("value") or ""
                    opt_label = label_text or opt_val
                    
                    if el_name in radio_groups:
                        radio_groups[el_name]["options"].append({
                            "value": opt_val,
                            "text": opt_label,
                            "selector": f"input[name='{el_name}'][value='{opt_val}']"
                        })
                        if required:
                            radio_groups[el_name]["required"] = True
                        continue
                    else:
                        group_label = await el.evaluate("""el => {
                            let fieldset = el.closest('fieldset');
                            if (fieldset) {
                                let legend = fieldset.querySelector('legend');
                                if (legend) return legend.innerText;
                            }
                            let parent = el.parentElement;
                            if (parent) return parent.innerText.split('\\n')[0];
                            return '';
                        }""")
                        group_label = group_label.strip() or el_name
                        
                        field_dict = {
                            "index": len(fields),
                            "selector": f"input[name='{el_name}']",
                            "tag_name": "input",
                            "type": "radio",
                            "id": el_id,
                            "name": el_name,
                            "placeholder": placeholder,
                            "label": group_label[:100],
                            "aria_label": aria_label,
                            "required": required,
                            "options": [{
                                "value": opt_val,
                                "text": opt_label,
                                "selector": f"input[name='{el_name}'][value='{opt_val}']"
                            }],
                            "multi_step": is_multi_step
                        }
                        radio_groups[el_name] = field_dict
                        fields.append(field_dict)
                        continue
                
                fields.append({
                    "index": len(fields),
                    "selector": f"{tag_name}[name='{el_name}']" if el_name else (f"#{el_id}" if el_id else f"{tag_name}:nth-of-type({idx+1})"),
                    "tag_name": tag_name,
                    "type": el_type,
                    "id": el_id,
                    "name": el_name,
                    "placeholder": placeholder,
                    "label": label_text[:100],
                    "aria_label": aria_label,
                    "required": required,
                    "options": options,
                    "multi_step": is_multi_step
                })
            except Exception as e:
                logger.warning(f"Failed extracting element details: {e}")
                
        return fields

    @staticmethod
    async def fill_fields(page: Page, field_values: Dict[str, Any], resume_bytes: Optional[bytes] = None, resume_filename: Optional[str] = None) -> int:
        """Automate filling inputs, selects, and file uploads. Returns filled fields count."""
        filled_count = 0
        
        # Detect iframe context
        target = page
        for frame in page.frames:
            if "greenhouse.io/embed" in frame.url or "greenhouse.io/job_app" in frame.url or "greenhouse.io/job_board" in frame.url:
                target = frame
                break
                
        for selector, value in field_values.items():
            try:
                el = await target.query_selector(selector)
                if not el or not await el.is_visible():
                    continue
                    
                tag_name = await el.evaluate("el => el.tagName.toLowerCase()")
                el_type = await el.get_attribute("type") or "text"
                
                if el_type == "file" and resume_bytes:
                    suffix = ".pdf" if (resume_filename and resume_filename.endswith(".pdf")) else ""
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
                        temp.write(resume_bytes)
                        temp_path = temp.name
                        
                    try:
                        await el.set_input_files(temp_path)
                        filled_count += 1
                        logger.info(f"FormHandler: Successfully uploaded resume via selector: {selector}")
                    finally:
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass
                            
                elif tag_name == "select":
                    # Fetch valid options to match and avoid Playwright select_option timeouts
                    valid_options = await el.evaluate("""el => {
                        return Array.from(el.options).map(opt => ({
                            value: opt.value,
                            text: opt.text.trim()
                        }));
                    }""")
                    option_values = [opt["value"] for opt in valid_options]
                    
                    if str(value) in option_values:
                        await el.select_option(value=str(value))
                        filled_count += 1
                    else:
                        matched_val = None
                        val_lower = str(value).lower()
                        for opt in valid_options:
                            opt_text_lower = opt["text"].lower()
                            opt_val_lower = opt["value"].lower()
                            if opt_val_lower == val_lower or opt_text_lower == val_lower or val_lower in opt_text_lower or opt_text_lower in val_lower:
                                matched_val = opt["value"]
                                break
                        
                        if matched_val:
                            await el.select_option(value=matched_val)
                            filled_count += 1
                        else:
                            # Fallback: select first non-empty option to satisfy required dropdown validation
                            non_empty = [opt["value"] for opt in valid_options if opt["value"].strip()]
                            if non_empty:
                                await el.select_option(value=non_empty[0])
                                filled_count += 1
                    
                elif el_type == "radio":
                    if isinstance(value, (str, int, float)):
                        name_attr = await el.get_attribute("name")
                        if name_attr:
                            radio_el = await page.query_selector(f"input[name='{name_attr}'][value='{value}']")
                            if radio_el:
                                await radio_el.click()
                                filled_count += 1
                                continue
                    is_checked = await el.is_checked()
                    if (value is True and not is_checked) or (value is False and is_checked):
                        await el.click()
                        filled_count += 1
                        
                elif el_type == "checkbox":
                    is_checked = await el.is_checked()
                    if (value is True and not is_checked) or (value is False and is_checked):
                        await el.click()
                        filled_count += 1
                        
                else:
                    await el.fill("")
                    await el.type(str(value), delay=50)
                    filled_count += 1
                    
            except Exception as e:
                logger.warning(f"FormHandler: Error filling field '{selector}': {e}")
                
        return filled_count
