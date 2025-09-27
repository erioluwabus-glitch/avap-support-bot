#!/usr/bin/env python3
"""
Simple AVAP Bot Audit Script
Basic environment and service checks
"""
import os
import json
from datetime import datetime

def main():
    print('🔍 AVAP Bot Simple Audit')
    print('=' * 40)
    
    # Initialize report
    report = {
        'timestamp': datetime.now().isoformat(),
        'env_check': {'missing': [], 'present': []},
        'file_structure': {'status': 'UNKNOWN', 'files_found': []},
        'imports': {'status': 'UNKNOWN', 'errors': []},
        'recommendations': []
    }
    
    # 1) Environment Variables Check
    print('\n1. Environment Variables Check...')
    required_vars = [
        'BOT_TOKEN', 'SUPABASE_URL', 'SUPABASE_KEY', 'ADMIN_RESET_TOKEN', 
        'ADMIN_USER_ID', 'GOOGLE_CREDENTIALS_JSON', 'GOOGLE_SHEET_ID', 
        'SUPPORT_GROUP_ID', 'ASSIGNMENT_GROUP_ID', 'QUESTIONS_GROUP_ID', 
        'RENDER_EXTERNAL_URL'
    ]
    
    missing = []
    present = []
    for var in required_vars:
        if os.getenv(var):
            present.append(var)
        else:
            missing.append(var)
    
    report['env_check']['missing'] = missing
    report['env_check']['present'] = present
    
    if missing:
        print(f'❌ Missing: {missing}')
    else:
        print('✅ All required environment variables present')
    
    # 2) File Structure Check
    print('\n2. File Structure Check...')
    expected_files = [
        'avap_bot/bot.py',
        'avap_bot/handlers/__init__.py',
        'avap_bot/handlers/admin.py',
        'avap_bot/handlers/student.py',
        'avap_bot/handlers/grading.py',
        'avap_bot/handlers/tips.py',
        'avap_bot/handlers/webhook.py',
        'avap_bot/services/__init__.py',
        'avap_bot/services/supabase_service.py',
        'avap_bot/services/sheets_service.py',
        'avap_bot/services/systeme_service.py',
        'avap_bot/services/notifier.py',
        'avap_bot/utils/__init__.py',
        'avap_bot/utils/logging_config.py',
        'avap_bot/utils/run_blocking.py',
        'avap_bot/utils/validators.py',
        'avap_bot/web/__init__.py',
        'avap_bot/web/admin_endpoints.py',
        'requirements.txt',
        'Dockerfile'
    ]
    
    found_files = []
    missing_files = []
    
    for file_path in expected_files:
        if os.path.exists(file_path):
            found_files.append(file_path)
        else:
            missing_files.append(file_path)
    
    report['file_structure']['files_found'] = found_files
    report['file_structure']['missing_files'] = missing_files
    
    if missing_files:
        print(f'❌ Missing files: {missing_files}')
        report['file_structure']['status'] = 'INCOMPLETE'
    else:
        print('✅ All expected files present')
        report['file_structure']['status'] = 'COMPLETE'
    
    # 3) Import Check
    print('\n3. Import Check...')
    import_errors = []
    
    try:
        import avap_bot
        print('✅ avap_bot package imports')
    except Exception as e:
        import_errors.append(f'avap_bot: {str(e)}')
        print(f'❌ avap_bot import failed: {e}')
    
    try:
        from avap_bot.services import supabase_service
        print('✅ supabase_service imports')
    except Exception as e:
        import_errors.append(f'supabase_service: {str(e)}')
        print(f'❌ supabase_service import failed: {e}')
    
    try:
        from avap_bot.services import sheets_service
        print('✅ sheets_service imports')
    except Exception as e:
        import_errors.append(f'sheets_service: {str(e)}')
        print(f'❌ sheets_service import failed: {e}')
    
    try:
        from avap_bot.handlers import admin
        print('✅ admin handlers import')
    except Exception as e:
        import_errors.append(f'admin handlers: {str(e)}')
        print(f'❌ admin handlers import failed: {e}')
    
    report['imports']['errors'] = import_errors
    if import_errors:
        report['imports']['status'] = 'FAILED'
    else:
        report['imports']['status'] = 'PASSED'
    
    # 4) Requirements Check
    print('\n4. Requirements Check...')
    if os.path.exists('requirements.txt'):
        with open('requirements.txt', 'r') as f:
            requirements = f.read()
        
        critical_packages = [
            'python-telegram-bot',
            'fastapi',
            'uvicorn',
            'supabase',
            'httpx',
            'gspread',
            'apscheduler'
        ]
        
        missing_packages = []
        for package in critical_packages:
            if package not in requirements.lower():
                missing_packages.append(package)
        
        if missing_packages:
            print(f'❌ Missing packages: {missing_packages}')
        else:
            print('✅ All critical packages in requirements.txt')
    else:
        print('❌ requirements.txt not found')
    
    # 5) Dockerfile Check
    print('\n5. Dockerfile Check...')
    if os.path.exists('Dockerfile'):
        with open('Dockerfile', 'r') as f:
            dockerfile = f.read()
        
        if 'avap_bot.bot:app' in dockerfile:
            print('✅ Dockerfile has correct entrypoint')
        else:
            print('❌ Dockerfile entrypoint may be incorrect')
            report['recommendations'].append('Check Dockerfile CMD entrypoint')
    else:
        print('❌ Dockerfile not found')
    
    # 6) Final Report
    print('\n' + '=' * 40)
    print('📊 AUDIT SUMMARY')
    print('=' * 40)
    
    # Calculate overall health
    env_ok = len(missing) == 0
    files_ok = len(missing_files) == 0
    imports_ok = len(import_errors) == 0
    
    if env_ok and files_ok and imports_ok:
        print('🎉 OVERALL: HEALTHY - Ready for deployment')
    else:
        print('⚠️ OVERALL: ISSUES FOUND - Review recommendations')
    
    print(f'\n📋 Environment: {"✅" if env_ok else "❌"} ({len(present)}/{len(required_vars)} vars)')
    print(f'📋 Files: {"✅" if files_ok else "❌"} ({len(found_files)}/{len(expected_files)} files)')
    print(f'📋 Imports: {"✅" if imports_ok else "❌"} ({len(import_errors)} errors)')
    
    if report['recommendations']:
        print('\n🔧 Recommendations:')
        for rec in report['recommendations']:
            print(f'  - {rec}')
    
    # Save detailed report
    with open('audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f'\n📄 Detailed report saved to: audit_report.json')
    
    return report

if __name__ == '__main__':
    main()


